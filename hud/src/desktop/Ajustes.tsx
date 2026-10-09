import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { useHud } from "../lib/store";
import type { Preferencias } from "../lib/tipos";
import { Icone } from "../holograms/Glifos";
import { CadastroRosto, ParearCelular } from "./Telas";

function Chave({ ligado, aoMudar, rotulo, descricao }: { ligado: boolean; aoMudar: (v: boolean) => void; rotulo: string; descricao?: string }) {
  return (
    <div className="flex items-start justify-between gap-4 py-2">
      <span>
        <span className="block text-[15px] text-gelo">{rotulo}</span>
        {descricao && <span className="block text-xs text-aco leading-snug mt-0.5">{descricao}</span>}
      </span>
      <button
        type="button"
        role="switch"
        aria-checked={ligado}
        aria-label={rotulo}
        onClick={() => aoMudar(!ligado)}
        className={`relative mt-0.5 h-6 w-11 shrink-0 rounded-full border transition-colors ${ligado ? "border-[var(--luz)] bg-[rgb(var(--luz-rgb)/0.25)]" : "border-aco/50"}`}
      >
        <span className={`absolute top-0.5 size-4 rounded-full transition-all ${ligado ? "left-[22px] bg-[var(--luz)]" : "left-0.5 bg-aco"}`} />
      </button>
    </div>
  );
}

function Secao({ titulo, children }: { titulo: string; children: React.ReactNode }) {
  return (
    <section className="py-5 border-t border-aco/20 first:border-t-0">
      <h3 className="numeral text-2xl font-[300] text-[var(--luz)] mb-2">{titulo}</h3>
      {children}
    </section>
  );
}

const VOZES = [
  { valor: "", rotulo: "Padrão do arquivo .env" },
  { valor: "pt-BR-FranciscaNeural", rotulo: "Francisca (feminina)" },
  { valor: "pt-BR-ThalitaMultilingualNeural", rotulo: "Thalita (feminina)" },
  { valor: "pt-BR-AntonioNeural", rotulo: "Antônio (masculina)" },
];

interface Dispositivo {
  id: string;
  nome: string;
  visto: number;
}

interface ItemDiagnostico {
  nome: string;
  ok: boolean;
  detalhe: string;
  dica: string;
}

export default function Ajustes({ aoFechar }: { aoFechar: () => void }) {
  const prefs = useHud((s) => s.prefs);
  const rosto = useHud((s) => s.rosto);
  const temPin = useHud((s) => s.pin);
  const avisar = useHud((s) => s.acoes.avisar);
  const [dispositivos, setDispositivos] = useState<Dispositivo[]>([]);
  const [diagnostico, setDiagnostico] = useState<ItemDiagnostico[] | null>(null);
  const [modal, setModal] = useState<"rosto" | "parear" | null>(null);
  const [nome, setNome] = useState(prefs?.nome ?? "");
  const [tratamento, setTratamento] = useState(prefs?.tratamento ?? "");
  const [cidade, setCidade] = useState(prefs?.cidade_rotulo || prefs?.cidade || "");
  const [pinAtual, setPinAtual] = useState("");
  const [pinNovo, setPinNovo] = useState("");

  const carregarDispositivos = () => api<Dispositivo[]>("/api/dispositivos").then(setDispositivos).catch(() => {});
  useEffect(() => {
    carregarDispositivos();
    api<ItemDiagnostico[]>("/api/diagnostico").then(setDiagnostico).catch(() => {});
    const tecla = (e: KeyboardEvent) => e.key === "Escape" && !modal && aoFechar();
    window.addEventListener("keydown", tecla);
    return () => window.removeEventListener("keydown", tecla);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  if (!prefs) return null;
  const mudar = (valores: Partial<Preferencias> & Record<string, unknown>, mensagem?: string) =>
    api("/api/preferencias", { method: "PATCH", json: valores })
      .then(() => mensagem && avisar(mensagem, "sucesso"))
      .catch((e) => avisar(e.message, "erro"));

  return (
    <div className="absolute inset-0 z-[3300]" role="dialog" aria-label="Ajustes">
      <button type="button" aria-label="Fechar ajustes" className="absolute inset-0 bg-tinta-funda/50 cursor-default" onClick={aoFechar} />
      <aside className="holo-corpo surgir absolute right-0 top-0 h-full w-[460px] overflow-y-auto rolagem px-7 py-6">
        <div className="flex items-center justify-between">
          <h2 className="numeral text-[34px] font-[300] text-gelo">Ajustes</h2>
          <button type="button" aria-label="Fechar" onClick={aoFechar} className="p-1 text-aco hover:text-gelo">
            <Icone.Fechar tamanho={20} />
          </button>
        </div>

        <Secao titulo="Você">
          <form
            className="space-y-3"
            onSubmit={(e) => {
              e.preventDefault();
              mudar({ nome: nome.trim(), tratamento: tratamento.trim() || "chefe", cidade: cidade.trim() }, "Salvo.");
            }}
          >
            {[
              ["Nome", nome, setNome],
              ["Como ela te chama", tratamento, setTratamento],
              ["Cidade", cidade, setCidade],
            ].map(([rotulo, valor, definir]) => (
              <label key={rotulo as string} className="block">
                <span className="text-xs text-aco">{rotulo as string}</span>
                <input
                  value={valor as string}
                  onChange={(e) => (definir as (v: string) => void)(e.target.value)}
                  className="mt-0.5 block w-full bg-transparent border-b border-aco/50 py-1 text-gelo outline-none focus:border-[var(--luz)]"
                />
              </label>
            ))}
            <button type="submit" className="text-sm text-[var(--luz)] hover:text-gelo">
              Salvar
            </button>
          </form>
        </Secao>

        <Secao titulo="Segurança">
          <Chave
            rotulo="Só obedecer ao meu rosto"
            descricao={rosto?.cadastrado ? "Confere seu rosto ao voltar do bloqueio do Windows e de tempos em tempos." : "Cadastre seu rosto para ativar."}
            ligado={prefs.bloqueio_facial}
            aoMudar={(v) => mudar({ bloqueio_facial: v })}
          />
          <Chave
            rotulo="Exigir uma piscada"
            descricao="Impede que uma foto engane a câmera ao desbloquear."
            ligado={prefs.exigir_piscada}
            aoMudar={(v) => mudar({ exigir_piscada: v })}
          />
          <label className="flex items-center justify-between py-2">
            <span className="text-[15px] text-gelo">Conferir o rosto de novo depois de</span>
            <select
              value={prefs.sessao_minutos}
              onChange={(e) => mudar({ sessao_minutos: Number(e.target.value) })}
              className="bg-tinta border border-aco/40 rounded px-2 py-1 text-gelo"
            >
              {[5, 15, 30, 60, 120, 480].map((m) => (
                <option key={m} value={m}>
                  {m < 60 ? `${m} min` : `${m / 60} h`}
                </option>
              ))}
            </select>
          </label>
          <div className="flex items-center gap-4 py-2 text-sm">
            <span className="text-aco flex-1">
              {rosto?.cadastrado ? `Rosto cadastrado${rosto.data ? ` em ${rosto.data}` : ""}.` : "Nenhum rosto cadastrado."}
            </span>
            <button type="button" onClick={() => setModal("rosto")} className="text-[var(--luz)] hover:text-gelo">
              {rosto?.cadastrado ? "Cadastrar de novo" : "Cadastrar"}
            </button>
            {rosto?.cadastrado && (
              <button
                type="button"
                className="text-aco hover:text-coral"
                onClick={() =>
                  window.confirm("Apagar o cadastro do seu rosto?") &&
                  api("/api/rosto", { method: "DELETE" })
                    .then((info: any) => useHud.setState({ rosto: info }))
                    .catch((e) => avisar(e.message, "erro"))
                }
              >
                Apagar
              </button>
            )}
          </div>
          <form
            className="flex items-end gap-3 pt-2"
            onSubmit={(e) => {
              e.preventDefault();
              api("/api/pin", { method: "POST", json: { pin: pinNovo, pin_atual: pinAtual } })
                .then((r: any) => {
                  useHud.setState({ pin: r.pin });
                  setPinAtual("");
                  setPinNovo("");
                  avisar(r.pin ? "PIN definido." : "PIN removido.", "sucesso");
                })
                .catch((erro) => avisar(erro.message, "erro"));
            }}
          >
            {temPin && (
              <label className="flex-1">
                <span className="text-xs text-aco">PIN atual</span>
                <input type="password" inputMode="numeric" value={pinAtual} onChange={(e) => setPinAtual(e.target.value)} className="block w-full bg-transparent border-b border-aco/50 py-1 text-gelo outline-none focus:border-[var(--luz)]" />
              </label>
            )}
            <label className="flex-1">
              <span className="text-xs text-aco">{temPin ? "Novo PIN (vazio remove)" : "PIN de 4 a 8 números"}</span>
              <input type="password" inputMode="numeric" value={pinNovo} onChange={(e) => setPinNovo(e.target.value)} className="block w-full bg-transparent border-b border-aco/50 py-1 text-gelo outline-none focus:border-[var(--luz)]" />
            </label>
            <button type="submit" className="text-sm text-[var(--luz)] hover:text-gelo pb-1">
              {temPin ? "Trocar" : "Definir"}
            </button>
          </form>
          <p className="text-xs text-aco mt-2 leading-snug">
            O PIN desbloqueia a Sexta-Feira pelo celular ou quando a câmera não estiver disponível. A tela de bloqueio do Windows continua com o Windows Hello.
          </p>
        </Secao>

        <Secao titulo="Voz e conversa">
          <label className="flex items-center justify-between py-2">
            <span className="text-[15px] text-gelo">Voz</span>
            <select value={prefs.voz} onChange={(e) => mudar({ voz: e.target.value })} className="bg-tinta border border-aco/40 rounded px-2 py-1 text-gelo">
              {VOZES.map((v) => (
                <option key={v.valor} value={v.valor}>
                  {v.rotulo}
                </option>
              ))}
            </select>
          </label>
          <Chave
            rotulo="Continuar ouvindo depois de responder"
            descricao='Por alguns segundos você pode falar de novo sem dizer "Sexta-Feira".'
            ligado={prefs.modo_continuacao}
            aoMudar={(v) => mudar({ modo_continuacao: v })}
          />
          <Chave
            rotulo="Atalhos rápidos"
            descricao='Comandos simples ("pausa", "volume 40", "modo jogo") sem passar pela IA.'
            ligado={prefs.atalhos_rapidos}
            aoMudar={(v) => mudar({ atalhos_rapidos: v })}
          />
          <Chave rotulo="Cumprimentar ao iniciar" ligado={prefs.saudacao_ao_iniciar} aoMudar={(v) => mudar({ saudacao_ao_iniciar: v })} />
        </Secao>

        <Secao titulo="Hologramas">
          <div className="flex gap-2 py-2">
            {(
              [
                ["sexta", "Âmbar"],
                ["jarvis", "Ciano"],
              ] as const
            ).map(([tema, rotulo]) => (
              <button
                key={tema}
                type="button"
                aria-pressed={prefs.tema === tema}
                onClick={() => mudar({ tema })}
                className={`px-4 py-1.5 rounded-full border text-sm ${prefs.tema === tema ? "border-[var(--luz)] text-[var(--luz)]" : "border-aco/40 text-aco hover:text-gelo"}`}
              >
                {rotulo}
              </button>
            ))}
          </div>
          <label className="block py-2">
            <span className="flex justify-between text-[15px] text-gelo">
              Sensibilidade das mãos <span className="numeral text-[var(--luz)]">{prefs.maos_sensibilidade.toFixed(1)}×</span>
            </span>
            <input
              type="range"
              min={0.6}
              max={1.8}
              step={0.1}
              value={prefs.maos_sensibilidade}
              onChange={(e) => mudar({ maos_sensibilidade: Number(e.target.value) })}
              className="w-full accent-[var(--luz)]"
            />
            <span className="text-xs text-aco">Maior = menos movimento para atravessar a tela.</span>
          </label>
          <button
            type="button"
            className="text-sm text-[var(--luz)] hover:text-gelo"
            onClick={() => {
              try {
                window.localStorage.removeItem("sexta.layout.v1");
              } catch {
                /* ignorado */
              }
              avisar("Posições esquecidas. Os próximos hologramas voltam ao arco em volta do núcleo.", "sucesso");
            }}
          >
            Esquecer posições dos hologramas
          </button>
        </Secao>

        <Secao titulo="Celulares">
          {dispositivos.length ? (
            <ul className="space-y-1">
              {dispositivos.map((d) => (
                <li key={d.id} className="flex items-center justify-between text-sm">
                  <span className="text-gelo">
                    {d.nome} <span className="text-aco text-xs">visto {new Date(d.visto * 1000).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" })}</span>
                  </span>
                  <button
                    type="button"
                    className="text-aco hover:text-coral text-xs"
                    onClick={() => api(`/api/dispositivos/${d.id}`, { method: "DELETE" }).then(() => carregarDispositivos())}
                  >
                    Remover
                  </button>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-aco">Nenhum celular pareado.</p>
          )}
          <button type="button" onClick={() => setModal("parear")} className="mt-3 text-sm text-[var(--luz)] hover:text-gelo">
            Parear um celular
          </button>
        </Secao>

        <Secao titulo="Rotinas e apelidos">
          <p className="text-sm text-aco leading-snug">Edite config/rotinas.yaml e config/apps.yaml na pasta da Sexta-Feira e recarregue.</p>
          <button
            type="button"
            className="mt-2 text-sm text-[var(--luz)] hover:text-gelo"
            onClick={() =>
              api<any[]>("/api/rotinas/recarregar", { method: "POST" })
                .then((r) => {
                  useHud.setState({ rotinas: r });
                  avisar(`${r.length} rotinas carregadas.`, "sucesso");
                })
                .catch((e) => avisar(e.message, "erro"))
            }
          >
            Recarregar arquivos
          </button>
        </Secao>

        <Secao titulo="Diagnóstico">
          {!diagnostico ? (
            <p className="text-sm text-aco">Verificando…</p>
          ) : (
            <ul className="space-y-2">
              {diagnostico.map((item) => (
                <li key={item.nome} className="text-sm">
                  <span className={item.ok ? "text-menta" : "text-coral"}>{item.ok ? "Funcionando" : "Atenção"}</span>
                  <span className="text-gelo"> {item.nome}</span>
                  <span className="block text-xs text-aco">{item.detalhe}</span>
                  {item.dica && <span className="block text-xs text-[var(--luz)]">{item.dica}</span>}
                </li>
              ))}
            </ul>
          )}
        </Secao>
      </aside>

      {modal && (
        <div className="absolute inset-0 z-10 grid place-items-center bg-tinta-funda/70 backdrop-blur-sm">
          <section className="holo-corpo surgir px-8 py-7" style={{ width: modal === "parear" ? 700 : 560 }}>
            <div className="flex items-center justify-between mb-5">
              <h2 className="numeral text-[30px] font-[300] text-gelo">{modal === "rosto" ? "Cadastro do rosto" : "Parear celular"}</h2>
              <button
                type="button"
                aria-label="Fechar"
                onClick={() => {
                  if (modal === "rosto") api("/api/rosto/cancelar", { method: "POST" }).catch(() => {});
                  setModal(null);
                  carregarDispositivos();
                }}
                className="p-1 text-aco hover:text-gelo"
              >
                <Icone.Fechar tamanho={20} />
              </button>
            </div>
            {modal === "rosto" ? <CadastroRosto aoTerminar={() => setModal(null)} /> : <ParearCelular />}
          </section>
        </div>
      )}
    </div>
  );
}

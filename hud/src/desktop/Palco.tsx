// Palco dos hologramas: posições em 3D, arrastar com mouse/toque e controle pelas mãos.
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { api } from "../lib/api";
import { CONEXOES, LeitorMaos, deltaAngulo, type LeituraMao } from "../lib/gestos";
import { tempoReal, useHud } from "../lib/store";
import type { Holograma } from "../lib/tipos";
import Clima from "../holograms/Clima";
import { GlifoTipo, Icone } from "../holograms/Glifos";
import { hologramaExtra } from "../extensoes";
import Globo from "../holograms/Globo";
import { Atividades, Camera, Imagem, Lembretes, Nota, Protocolo, Rotinas } from "../holograms/Listas";
import Noticias from "../holograms/Noticias";
import Relogio from "../holograms/Relogio";
import Sistema from "../holograms/Sistema";
import Jornal from "../holograms/Jornal";
import { Foco, Plano, Tarefas } from "../holograms/Planejamento";
import { ALTURA_NUCLEO } from "./Nucleo";

export interface Pose {
  x: number;
  y: number;
  z: number;
  rx: number;
  ry: number;
  rz: number;
  s: number;
}

// Posições iniciais num arco em volta do núcleo (frações da tela), inclinadas para o centro.
// Evita o relógio (canto superior esquerdo), o status (superior direito) e a barra de comando.
const VAGAS = [
  { x: -0.3, y: 0.03, ry: 16 },
  { x: 0.31, y: -0.06, ry: -16 },
  { x: 0.31, y: 0.32, ry: -12 },
  { x: -0.3, y: 0.38, ry: 12 },
  { x: 0, y: -0.32, ry: 0 },
  { x: -0.14, y: 0.42, ry: 5 },
  { x: 0.14, y: 0.42, ry: -5 },
];
const CHAVE_LAYOUT = "sexta.layout.v1";
const limitar = (v: number, a: number, b: number) => Math.min(b, Math.max(a, v));

function lerLayout(): Record<string, Pose> {
  try {
    return JSON.parse(window.localStorage.getItem(CHAVE_LAYOUT) ?? "{}");
  } catch {
    return {};
  }
}

class GerentePalco {
  elementos = new Map<string, HTMLElement>();
  tipos = new Map<string, string>();
  poses = new Map<string, Pose>();
  alvos = new Map<string, Pose>();
  antesDoFoco = new Map<string, Pose>();
  destacados = new Set<string>();
  layout = lerLayout();
  aoFechar: (id: string) => void = () => {};

  private tela() {
    return { l: window.innerWidth, a: window.innerHeight };
  }

  montar(id: string, tipo: string, el: HTMLElement) {
    this.elementos.set(id, el);
    this.tipos.set(id, tipo);
    if (!this.poses.has(id)) {
      const salva = this.layout[tipo];
      const pose = salva ? { ...salva } : this.vagaLivre();
      this.poses.set(id, { ...pose });
      this.alvos.set(id, { ...pose });
    }
    this.escrever(id);
  }

  desmontar(id: string) {
    this.elementos.delete(id);
    this.poses.delete(id);
    this.alvos.delete(id);
    this.tipos.delete(id);
    this.antesDoFoco.delete(id);
  }

  private vagaLivre(): Pose {
    const { l, a } = this.tela();
    const ocupadas = [...this.alvos.values()];
    const distancia = (vaga: (typeof VAGAS)[number]) =>
      ocupadas.length ? Math.min(...ocupadas.map((p) => Math.hypot(p.x - vaga.x * l, p.y - vaga.y * a))) : Infinity;
    // a primeira vaga livre, na ordem; se todas estiverem ocupadas, a menos congestionada
    let melhor = VAGAS.find((vaga) => distancia(vaga) > 300) ?? VAGAS[0];
    if (distancia(melhor) <= 300) {
      melhor = VAGAS.reduce((a1, a2) => (distancia(a2) > distancia(a1) ? a2 : a1));
    }
    return { x: melhor.x * l, y: melhor.y * a, z: -40, rx: 0, ry: melhor.ry, rz: 0, s: a < 900 ? 0.82 : 0.92 };
  }

  alvo(id: string): Pose | undefined {
    return this.alvos.get(id);
  }

  mover(id: string, parcial: Partial<Pose>, imediato = false) {
    const alvo = this.alvos.get(id);
    if (!alvo) return;
    Object.assign(alvo, parcial);
    alvo.z = limitar(alvo.z, -700, 420);
    alvo.s = limitar(alvo.s, 0.35, 2.8);
    alvo.ry = limitar(alvo.ry, -75, 75);
    if (imediato) {
      this.poses.set(id, { ...alvo });
      this.escrever(id);
    }
  }

  passo(dt: number) {
    const k = 1 - Math.exp(-dt * 14);
    for (const [id, alvo] of this.alvos) {
      const pose = this.poses.get(id)!;
      let mudou = false;
      for (const chave of ["x", "y", "z", "rx", "ry", "rz", "s"] as const) {
        const d = alvo[chave] - pose[chave];
        if (Math.abs(d) > 0.01) {
          pose[chave] += d * k;
          mudou = true;
        }
      }
      if (mudou) this.escrever(id);
    }
  }

  escrever(id: string) {
    const el = this.elementos.get(id);
    const p = this.poses.get(id);
    if (!el || !p) return;
    el.style.transform = `translate(-50%, -50%) translate3d(${p.x.toFixed(1)}px, ${p.y.toFixed(1)}px, ${p.z.toFixed(1)}px) rotateX(${p.rx.toFixed(2)}deg) rotateY(${p.ry.toFixed(2)}deg) rotateZ(${p.rz.toFixed(2)}deg) scale(${p.s.toFixed(3)})`;
    el.style.zIndex = String(Math.round(1000 + p.z));
  }

  salvar(id: string) {
    const tipo = this.tipos.get(id);
    const alvo = this.alvos.get(id);
    if (!tipo || !alvo || this.antesDoFoco.has(id)) return;
    this.layout[tipo] = { ...alvo };
    try {
      window.localStorage.setItem(CHAVE_LAYOUT, JSON.stringify(this.layout));
    } catch {
      /* sem armazenamento: só não lembra a posição */
    }
  }

  alternarFoco(id: string) {
    const alvo = this.alvos.get(id);
    if (!alvo) return;
    const anterior = this.antesDoFoco.get(id);
    if (anterior) {
      this.antesDoFoco.delete(id);
      this.mover(id, anterior);
    } else {
      this.antesDoFoco.set(id, { ...alvo });
      this.mover(id, { x: 0, y: -window.innerHeight * 0.02, z: 160, rx: 0, ry: 0, rz: 0, s: Math.max(alvo.s, 1.15) });
    }
  }

  destacar(ids: Set<string>) {
    for (const [id, el] of this.elementos) {
      const ativo = ids.has(id);
      if (ativo !== this.destacados.has(id)) el.dataset.ativo = String(ativo);
    }
    this.destacados = new Set(ids);
  }

  idEm(x: number, y: number): string | null {
    for (const el of document.elementsFromPoint(x, y)) {
      const holo = (el as HTMLElement).closest?.("[data-holo-id]") as HTMLElement | null;
      if (holo) return holo.dataset.holoId ?? null;
    }
    return null;
  }

  saiuDaTela(id: string, vx: number, vy: number): boolean {
    const p = this.alvos.get(id);
    if (!p) return false;
    const velocidade = Math.hypot(vx, vy);
    const paraFora = p.x * vx + p.y * vy > 0;
    return velocidade > 2600 && paraFora;
  }
}

function Conteudo({ holo }: { holo: Holograma }) {
  switch (holo.tipo) {
    case "clima":
      return <Clima dados={holo.dados} />;
    case "noticias":
      return <Noticias dados={holo.dados} />;
    case "sistema":
      return <Sistema dados={holo.dados} />;
    case "relogio":
      return <Relogio />;
    case "globo":
      return <Globo dados={holo.dados} />;
    case "lembretes":
      return <Lembretes />;
    case "rotinas":
      return <Rotinas />;
    case "camera":
      return <Camera />;
    case "atividades":
      return <Atividades dados={holo.dados} />;
    case "protocolo":
      return <Protocolo dados={holo.dados} />;
    case "jornal":
      return <Jornal dados={holo.dados} />;
    case "tarefas":
      return <Tarefas dados={holo.dados} />;
    case "plano":
      return <Plano dados={holo.dados} />;
    case "foco":
      return <Foco dados={holo.dados} />;
    case "imagem":
      return <Imagem dados={holo.dados} />;
    default: {
      const Extra = hologramaExtra(holo.tipo)?.componente;
      return Extra ? <Extra dados={holo.dados} /> : <Nota dados={holo.dados} />;
    }
  }
}

const INTERATIVO = "button, a, input, textarea, select, [data-clicavel], [data-girar]";

function HologramaVivo({ holo, saindo, gerente }: { holo: Holograma; saindo: boolean; gerente: GerentePalco }) {
  const ref = useRef<HTMLDivElement>(null);
  const toques = useRef(new Map<number, { x: number; y: number }>());
  const inicio = useRef<{ pose: Pose; distancia?: number; angulo?: number; historico: { x: number; y: number; t: number }[] } | null>(null);

  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    gerente.montar(holo.id, holo.tipo, el);
    return () => gerente.desmontar(holo.id);
  }, [gerente, holo.id, holo.tipo]);

  const aoApertar = (e: React.PointerEvent) => {
    if ((e.target as HTMLElement).closest(INTERATIVO)) return;
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    toques.current.set(e.pointerId, { x: e.clientX, y: e.clientY });
    const pose = { ...gerente.alvo(holo.id)! };
    const pontos = [...toques.current.values()];
    if (pontos.length === 2) {
      const [a, b] = pontos;
      inicio.current = { pose, distancia: Math.hypot(b.x - a.x, b.y - a.y), angulo: Math.atan2(b.y - a.y, b.x - a.x), historico: [] };
    } else {
      inicio.current = { pose, historico: [{ x: e.clientX, y: e.clientY, t: performance.now() }] };
    }
    gerente.destacar(new Set([holo.id]));
  };

  const aoMover = (e: React.PointerEvent) => {
    if (!toques.current.has(e.pointerId) || !inicio.current) return;
    const anterior = toques.current.get(e.pointerId)!;
    toques.current.set(e.pointerId, { x: e.clientX, y: e.clientY });
    const pontos = [...toques.current.values()];
    const ini = inicio.current;
    if (pontos.length === 2 && ini.distancia) {
      const [a, b] = pontos;
      const d = Math.hypot(b.x - a.x, b.y - a.y);
      const ang = Math.atan2(b.y - a.y, b.x - a.x);
      gerente.mover(holo.id, { s: ini.pose.s * (d / ini.distancia), rz: ini.pose.rz + (deltaAngulo(ang, ini.angulo!) * 180) / Math.PI }, true);
      return;
    }
    const alvo = gerente.alvo(holo.id)!;
    gerente.mover(holo.id, { x: alvo.x + e.clientX - anterior.x, y: alvo.y + e.clientY - anterior.y }, true);
    ini.historico.push({ x: e.clientX, y: e.clientY, t: performance.now() });
    if (ini.historico.length > 8) ini.historico.shift();
  };

  const aoSoltar = (e: React.PointerEvent) => {
    toques.current.delete(e.pointerId);
    const ini = inicio.current;
    if (toques.current.size === 0 && ini) {
      const h = ini.historico;
      if (h.length >= 2) {
        const a = h[0];
        const b = h[h.length - 1];
        const dt = Math.max(1, b.t - a.t) / 1000;
        if (gerente.saiuDaTela(holo.id, (b.x - a.x) / dt, (b.y - a.y) / dt)) {
          gerente.aoFechar(holo.id);
          return;
        }
      }
      gerente.salvar(holo.id);
      inicio.current = null;
      gerente.destacar(new Set());
    }
  };

  return (
    <div
      ref={ref}
      className="holo"
      data-holo-id={holo.id}
      onPointerDown={aoApertar}
      onPointerMove={aoMover}
      onPointerUp={aoSoltar}
      onPointerCancel={aoSoltar}
      onWheel={(e) => {
        const rolavel = (e.target as HTMLElement).closest(".rolagem") as HTMLElement | null;
        if (rolavel && rolavel.scrollHeight > rolavel.clientHeight + 2) return; // rola a lista em vez de ampliar
        const alvo = gerente.alvo(holo.id);
        if (!alvo) return;
        if (e.shiftKey) gerente.mover(holo.id, { ry: alvo.ry + e.deltaY * 0.05 });
        else gerente.mover(holo.id, { s: alvo.s * Math.exp(-e.deltaY * 0.0012) });
        gerente.salvar(holo.id);
      }}
    >
      <div className="holo-flutua" style={{ animationDelay: `${(holo.criado % 7) * -1}s` }}>
        <div className={saindo ? "holo-saida" : "holo-entrada"}>
          <section className="holo-corpo" aria-label={holo.titulo}>
            <header
              className="flex items-center gap-2.5 px-4 pt-3 pb-2 select-none cursor-grab active:cursor-grabbing"
              onDoubleClick={() => gerente.alternarFoco(holo.id)}
            >
              {hologramaExtra(holo.tipo)?.glifo ? (
                <span className="text-[var(--luz)] shrink-0">{hologramaExtra(holo.tipo)!.glifo!(17)}</span>
              ) : (
                <GlifoTipo tipo={holo.tipo} tamanho={17} className="text-[var(--luz)] shrink-0" />
              )}
              <h2 className="text-[13px] font-medium text-gelo/85 truncate max-w-[300px]">{holo.titulo}</h2>
              <button
                type="button"
                aria-label="Ampliar ou voltar"
                title="Ampliar (ou dê dois cliques no título)"
                className="ml-auto p-1 text-aco hover:text-gelo"
                onClick={() => gerente.alternarFoco(holo.id)}
              >
                <Icone.Foco tamanho={15} />
              </button>
              <button type="button" aria-label={`Fechar ${holo.titulo}`} className="p-1 text-aco hover:text-coral" onClick={() => gerente.aoFechar(holo.id)}>
                <Icone.Fechar tamanho={16} />
              </button>
            </header>
            <div className="px-4 pb-4">
              <Conteudo holo={holo} />
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}

interface EstadoMao {
  segurando: string | null;
  girar: HTMLElement | null;
  clicavel: HTMLElement | null;
  inicioPinca: number;
  x0: number;
  y0: number;
  ultimoX: number;
  ultimoY: number;
  pose0: Pose | null;
  escala0: number;
  rolagem0: number;
  historico: { x: number; y: number; t: number }[];
  dwellAlvo: Element | null;
  dwellInicio: number;
  paradoDesde: number;
  paradoX: number;
  paradoY: number;
  pausaAte: number;
  escalaDupla: { distancia: number; angulo: number; s0: number; rz0: number } | null;
  visto: number;
}

const novoEstadoMao = (): EstadoMao => ({
  segurando: null,
  girar: null,
  clicavel: null,
  inicioPinca: 0,
  x0: 0,
  y0: 0,
  ultimoX: 0,
  ultimoY: 0,
  pose0: null,
  escala0: 1,
  rolagem0: 0,
  historico: [],
  dwellAlvo: null,
  dwellInicio: 0,
  paradoDesde: 0,
  paradoX: 0,
  paradoY: 0,
  pausaAte: 0,
  escalaDupla: null,
  visto: 0,
});

function clicavelEm(x: number, y: number): HTMLElement | null {
  for (const el of document.elementsFromPoint(x, y)) {
    const alvo = (el as HTMLElement).closest?.("button, a, [data-clicavel]") as HTMLElement | null;
    if (alvo) return alvo;
  }
  return null;
}

/** Laço das mãos: lê os pontos, interpreta os gestos, move hologramas e desenha a sobreposição. */
function useMaos(gerente: GerentePalco, tela: React.RefObject<HTMLCanvasElement | null>) {
  const ligadas = useHud((s) => s.maosLigadas);
  const sensibilidade = useHud((s) => s.prefs?.maos_sensibilidade ?? 1);

  useEffect(() => {
    const leitor = new LeitorMaos();
    const estados = new Map<string, EstadoMao>();
    let quadro = 0;
    let anterior = performance.now();
    let opacidade = 0;

    const laco = (agora: number) => {
      quadro = requestAnimationFrame(laco);
      const dt = Math.min(0.1, (agora - anterior) / 1000);
      anterior = agora;
      gerente.passo(dt);

      const canvas = tela.current;
      const ctx = canvas?.getContext("2d");
      if (!canvas || !ctx) return;
      const dpr = window.devicePixelRatio || 1;
      const l = window.innerWidth;
      const a = window.innerHeight;
      if (canvas.width !== Math.round(l * dpr)) {
        canvas.width = Math.round(l * dpr);
        canvas.height = Math.round(a * dpr);
      }
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, l, a);

      const recente = agora - tempoReal.maosEm < 400;
      const leituras: LeituraMao[] = ligadas && recente ? leitor.ler(tempoReal.maos, l, a, sensibilidade, agora) : [];
      opacidade += ((leituras.length ? 1 : 0) - opacidade) * Math.min(1, dt * 8);
      const destacados = new Set<string>();

      for (const m of leituras) {
        let e = estados.get(m.id);
        if (!e || agora - e.visto > 600) {
          e = novoEstadoMao();
          estados.set(m.id, e);
        }
        e.visto = agora;
        processarMao(m, e, leituras, estados, agora, destacados);
      }
      for (const [id, e] of estados) {
        if (agora - e.visto > 600) {
          if (e.segurando) gerente.salvar(e.segurando);
          estados.delete(id);
        } else if (e.segurando) destacados.add(e.segurando);
      }
      gerente.destacar(destacados);
      if (opacidade > 0.02) desenhar(ctx, leituras, estados, opacidade, agora);
    };

    const processarMao = (m: LeituraMao, e: EstadoMao, todas: LeituraMao[], estadosMaos: Map<string, EstadoMao>, agora: number, destacados: Set<string>) => {
      const pincava = e.inicioPinca > 0;
      if (m.pinca && !pincava) {
        e.inicioPinca = agora;
        e.x0 = e.ultimoX = m.x;
        e.y0 = e.ultimoY = m.y;
        e.historico = [];
        e.clicavel = clicavelEm(m.x, m.y);
        const id = gerente.idEm(m.x, m.y);
        const outra = [...estadosMaos.entries()].find(([outroId, s]) => outroId !== m.id && s.segurando && s.inicioPinca > 0);
        if (outra && (!id || id === outra[1].segurando)) {
          // segunda mão: escala e gira o holograma que a primeira está segurando
          const mOutra = todas.find((t) => t.id === outra[0]);
          const alvo = gerente.alvo(outra[1].segurando!);
          if (mOutra && alvo) {
            outra[1].escalaDupla = {
              distancia: Math.hypot(m.x - mOutra.x, m.y - mOutra.y) || 1,
              angulo: Math.atan2(m.y - mOutra.y, m.x - mOutra.x),
              s0: alvo.s,
              rz0: alvo.rz,
            };
          }
        } else if (id) {
          e.segurando = id;
          e.pose0 = { ...gerente.alvo(id)! };
          e.escala0 = m.escala;
          e.rolagem0 = m.rolagem;
          const elemento = document.elementsFromPoint(m.x, m.y).find((el) => (el as HTMLElement).closest?.("[data-girar]"));
          e.girar = elemento ? ((elemento as HTMLElement).closest("[data-girar]") as HTMLElement) : null;
        }
      } else if (m.pinca && pincava) {
        const movimento = Math.hypot(m.x - e.x0, m.y - e.y0);
        e.historico.push({ x: m.x, y: m.y, t: agora });
        if (e.historico.length > 8) e.historico.shift();
        if (e.clicavel && movimento > 28) e.clicavel = null;
        if (e.segurando && !e.clicavel) {
          if (e.girar) {
            e.girar.dispatchEvent(new CustomEvent("girar", { detail: { dx: m.x - e.ultimoX, dy: m.y - e.ultimoY } }));
          } else if (e.pose0) {
            gerente.mover(e.segurando, {
              x: e.pose0.x + (m.x - e.x0),
              y: e.pose0.y + (m.y - e.y0),
              z: e.pose0.z + (m.escala / e.escala0 - 1) * 900,
              ry: e.pose0.ry + (deltaAngulo(m.rolagem, e.rolagem0) * 180) / Math.PI,
            });
            if (e.escalaDupla) {
              const outra = todas.find((t) => t.id !== m.id && t.pinca);
              if (outra) {
                const d = Math.hypot(outra.x - m.x, outra.y - m.y);
                const ang = Math.atan2(outra.y - m.y, outra.x - m.x);
                gerente.mover(e.segurando, {
                  s: e.escalaDupla.s0 * (d / e.escalaDupla.distancia),
                  rz: e.escalaDupla.rz0 + (deltaAngulo(ang, e.escalaDupla.angulo) * 180) / Math.PI,
                });
              } else {
                e.escalaDupla = null;
              }
            }
          }
          destacados.add(e.segurando);
        }
        e.ultimoX = m.x;
        e.ultimoY = m.y;
      } else if (!m.pinca && pincava) {
        const duracao = agora - e.inicioPinca;
        const movimento = Math.hypot(m.x - e.x0, m.y - e.y0);
        if (e.clicavel && duracao < 600 && movimento < 28) {
          e.clicavel.click();
        } else if (e.segurando) {
          const h = e.historico;
          let fechou = false;
          if (h.length >= 2) {
            const dtv = Math.max(1, h[h.length - 1].t - h[0].t) / 1000;
            const vx = (h[h.length - 1].x - h[0].x) / dtv;
            const vy = (h[h.length - 1].y - h[0].y) / dtv;
            if (!e.girar && gerente.saiuDaTela(e.segurando, vx, vy)) {
              gerente.aoFechar(e.segurando);
              fechou = true;
            }
          }
          if (!fechou) gerente.salvar(e.segurando);
        }
        Object.assign(e, { segurando: null, girar: null, clicavel: null, inicioPinca: 0, pose0: null, escalaDupla: null });
      }

      if (!m.pinca) {
        const id = gerente.idEm(m.x, m.y);
        if (id) destacados.add(id);
        // apontar e esperar = clicar
        if (m.gesto === "aponta" && agora > e.pausaAte) {
          const alvo = clicavelEm(m.x, m.y);
          if (alvo !== e.dwellAlvo) {
            e.dwellAlvo = alvo;
            e.dwellInicio = agora;
          } else if (alvo && agora - e.dwellInicio > 900) {
            alvo.click();
            e.dwellAlvo = null;
            e.pausaAte = agora + 900;
          }
        } else {
          e.dwellAlvo = null;
        }
        // mão aberta parada sobre um holograma = ampliar/voltar
        if (Math.hypot(m.x - e.paradoX, m.y - e.paradoY) > 30 || m.gesto !== "aberta") {
          e.paradoX = m.x;
          e.paradoY = m.y;
          e.paradoDesde = agora;
        } else if (id && agora - e.paradoDesde > 1300 && agora > e.pausaAte) {
          gerente.alternarFoco(id);
          e.pausaAte = agora + 1600;
          e.paradoDesde = agora;
        }
      }
    };

    const desenhar = (ctx: CanvasRenderingContext2D, leituras: LeituraMao[], estadosMaos: Map<string, EstadoMao>, alfa: number, agora: number) => {
      const luz = getComputedStyle(document.documentElement).getPropertyValue("--luz-rgb").trim().split(/\s+/).join(",") || "255,181,71";
      for (const m of leituras) {
        const e = estadosMaos.get(m.id);
        ctx.lineWidth = 1.4;
        ctx.strokeStyle = `rgba(${luz},${0.42 * alfa})`;
        ctx.beginPath();
        for (const [i, j] of CONEXOES) {
          ctx.moveTo(m.pontos[i][0], m.pontos[i][1]);
          ctx.lineTo(m.pontos[j][0], m.pontos[j][1]);
        }
        ctx.stroke();
        for (let i = 0; i < m.pontos.length; i++) {
          const ponta = i % 4 === 0 && i > 0;
          ctx.fillStyle = ponta ? `rgba(216,238,255,${0.9 * alfa})` : `rgba(${luz},${0.6 * alfa})`;
          ctx.beginPath();
          ctx.arc(m.pontos[i][0], m.pontos[i][1], ponta ? 3 : 1.8, 0, Math.PI * 2);
          ctx.fill();
        }
        // cursor
        ctx.shadowColor = `rgba(${luz},0.9)`;
        ctx.shadowBlur = 12;
        if (m.pinca) {
          ctx.fillStyle = `rgba(${luz},${alfa})`;
          ctx.beginPath();
          ctx.arc(m.x, m.y, 6, 0, Math.PI * 2);
          ctx.fill();
          ctx.strokeStyle = `rgba(${luz},${alfa})`;
          ctx.lineWidth = 2;
          ctx.beginPath();
          ctx.arc(m.x, m.y, 12, 0, Math.PI * 2);
          ctx.stroke();
        } else {
          const raio = 9 + limitar(m.razaoPinca, 0.3, 1.3) * 12;
          ctx.strokeStyle = `rgba(216,238,255,${0.85 * alfa})`;
          ctx.lineWidth = 1.5;
          ctx.beginPath();
          ctx.arc(m.x, m.y, raio, 0, Math.PI * 2);
          ctx.stroke();
          if (e?.dwellAlvo) {
            const progresso = limitar((agora - e.dwellInicio) / 900, 0, 1);
            ctx.strokeStyle = `rgba(${luz},${alfa})`;
            ctx.lineWidth = 3;
            ctx.beginPath();
            ctx.arc(m.x, m.y, raio + 6, -Math.PI / 2, -Math.PI / 2 + progresso * Math.PI * 2);
            ctx.stroke();
          }
        }
        ctx.shadowBlur = 0;
      }
    };

    quadro = requestAnimationFrame(laco);
    return () => cancelAnimationFrame(quadro);
  }, [gerente, tela, ligadas, sensibilidade]);
}

export default function Palco() {
  const hologramas = useHud((s) => s.hologramas);
  const avisar = useHud((s) => s.acoes.avisar);
  const [gerente] = useState(() => new GerentePalco());
  const tela = useRef<HTMLCanvasElement>(null);
  const [itens, setItens] = useState<{ holo: Holograma; saindo: boolean }[]>([]);

  // mantém os que estão saindo por um instante, para a animação de "desprojetar"
  useEffect(() => {
    setItens((atuais) => {
      const ids = new Set(hologramas.map((h) => h.id));
      const saindo = atuais.filter((i) => !ids.has(i.holo.id)).map((i) => ({ holo: i.holo, saindo: true }));
      return [...hologramas.map((h) => ({ holo: h, saindo: false })), ...saindo];
    });
    const t = window.setTimeout(() => setItens((atuais) => atuais.filter((i) => !i.saindo)), 320);
    return () => window.clearTimeout(t);
  }, [hologramas]);

  useEffect(() => {
    gerente.aoFechar = (id) => {
      const el = gerente.elementos.get(id)?.querySelector(".holo-entrada");
      el?.classList.replace("holo-entrada", "holo-saida");
      window.setTimeout(() => api(`/api/hologramas/${id}`, { method: "DELETE" }).catch((e) => avisar(e.message, "erro")), 220);
    };
  }, [gerente, avisar]);

  useMaos(gerente, tela);

  return (
    <>
      <div className="absolute inset-0" style={{ perspective: "1600px", perspectiveOrigin: `50% ${ALTURA_NUCLEO * 100}%` }}>
        {itens.map(({ holo, saindo }) => (
          <HologramaVivo key={holo.id} holo={holo} saindo={saindo} gerente={gerente} />
        ))}
      </div>
      <canvas ref={tela} className="absolute inset-0 size-full pointer-events-none" aria-hidden="true" />
    </>
  );
}

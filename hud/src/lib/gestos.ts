// Leitura das mãos: transforma os 21 pontos do MediaPipe em cursor + gesto na tela.
import type { Mao } from "./tipos";

/** Filtro "One Euro": suaviza o tremor sem atrasar movimentos rápidos. */
export class FiltroUmEuro {
  private xAnterior: number | null = null;
  private dxAnterior = 0;
  private tAnterior = 0;

  constructor(
    private corteMinimo = 1.2,
    private beta = 0.012,
    private corteDerivada = 1.0,
  ) {}

  private static alfa(corte: number, dt: number): number {
    const tau = 1 / (2 * Math.PI * corte);
    return 1 / (1 + tau / dt);
  }

  filtrar(x: number, t: number): number {
    if (this.xAnterior === null) {
      this.xAnterior = x;
      this.tAnterior = t;
      return x;
    }
    const dt = Math.max(1e-3, (t - this.tAnterior) / 1000);
    this.tAnterior = t;
    const dx = (x - this.xAnterior) / dt;
    const aD = FiltroUmEuro.alfa(this.corteDerivada, dt);
    const dxSuave = aD * dx + (1 - aD) * this.dxAnterior;
    const corte = this.corteMinimo + this.beta * Math.abs(dxSuave);
    const a = FiltroUmEuro.alfa(corte, dt);
    const xSuave = a * x + (1 - a) * this.xAnterior;
    this.xAnterior = xSuave;
    this.dxAnterior = dxSuave;
    return xSuave;
  }

  reiniciar(): void {
    this.xAnterior = null;
    this.dxAnterior = 0;
  }
}

export type Gesto = "pinca" | "aberta" | "punho" | "aponta" | "neutra";

export interface LeituraMao {
  id: string;
  x: number;
  y: number;
  escala: number;
  razaoPinca: number;
  pinca: boolean;
  gesto: Gesto;
  rolagem: number;
  pontos: [number, number][];
}

const distancia = (a: number[], b: number[]) => Math.hypot(a[0] - b[0], a[1] - b[1]);

const DEDOS: [number, number][] = [
  [8, 6],
  [12, 10],
  [16, 14],
  [20, 18],
];

export const CONEXOES: [number, number][] = [
  [0, 1], [1, 2], [2, 3], [3, 4], [0, 5], [5, 6], [6, 7], [7, 8], [5, 9], [9, 10], [10, 11], [11, 12],
  [9, 13], [13, 14], [14, 15], [15, 16], [13, 17], [17, 18], [18, 19], [19, 20], [0, 17],
];

interface Memoria {
  fx: FiltroUmEuro;
  fy: FiltroUmEuro;
  pinca: boolean;
  visto: number;
}

export class LeitorMaos {
  private memoria = new Map<string, Memoria>();

  /** ``sensibilidade`` > 1 = menos movimento da mão para cruzar a tela. */
  ler(maos: Mao[], largura: number, altura: number, sensibilidade: number, agora: number): LeituraMao[] {
    const metadeL = 0.34 / Math.max(0.4, sensibilidade);
    const metadeA = 0.3 / Math.max(0.4, sensibilidade);
    const paraTela = (px: number, py: number): [number, number] => [
      ((px - (0.5 - metadeL)) / (2 * metadeL)) * largura,
      ((py - (0.46 - metadeA)) / (2 * metadeA)) * altura,
    ];
    const vistas = new Set<string>();
    const leituras: LeituraMao[] = [];
    maos.forEach((mao, indice) => {
      const id = mao.lado === "?" ? `mao${indice}` : mao.lado;
      if (vistas.has(id)) return;
      vistas.add(id);
      const p = mao.p;
      const escala = distancia(p[0], p[9]) || 0.1;
      const razaoPinca = distancia(p[4], p[8]) / escala;
      let mem = this.memoria.get(id);
      if (!mem || agora - mem.visto > 500) {
        mem = { fx: new FiltroUmEuro(), fy: new FiltroUmEuro(), pinca: false, visto: agora };
        this.memoria.set(id, mem);
      }
      mem.visto = agora;
      mem.pinca = mem.pinca ? razaoPinca < 0.42 : razaoPinca < 0.3;

      const estendidos = DEDOS.map(([ponta, meio]) => distancia(p[0], p[ponta]) > distancia(p[0], p[meio]) * 1.12);
      let gesto: Gesto = "neutra";
      if (mem.pinca) gesto = "pinca";
      else if (estendidos.every(Boolean)) gesto = "aberta";
      else if (!estendidos.some(Boolean)) gesto = "punho";
      else if (estendidos[0] && !estendidos[1] && !estendidos[2] && !estendidos[3]) gesto = "aponta";

      const alvo = gesto === "aponta" ? p[8] : [(p[4][0] + p[8][0]) / 2, (p[4][1] + p[8][1]) / 2];
      const [tx, ty] = paraTela(alvo[0], alvo[1]);
      const x = Math.min(largura, Math.max(0, mem.fx.filtrar(tx, agora)));
      const y = Math.min(altura, Math.max(0, mem.fy.filtrar(ty, agora)));
      const pontos = p.map((q) => paraTela(q[0], q[1]));
      const rolagem = Math.atan2(p[17][1] - p[5][1], p[17][0] - p[5][0]);
      leituras.push({ id, x, y, escala, razaoPinca, pinca: mem.pinca, gesto, rolagem, pontos });
    });
    for (const [id, mem] of this.memoria) {
      if (!vistas.has(id) && agora - mem.visto > 1500) this.memoria.delete(id);
    }
    return leituras;
  }
}

/** Diferença entre dois ângulos, no intervalo (-π, π]. */
export function deltaAngulo(a: number, b: number): number {
  let d = a - b;
  while (d > Math.PI) d -= 2 * Math.PI;
  while (d <= -Math.PI) d += 2 * Math.PI;
  return d;
}

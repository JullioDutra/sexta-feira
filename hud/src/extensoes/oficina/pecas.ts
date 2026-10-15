// Separa uma malha única (STL) em peças: triângulos ligados por vértices na mesma posição formam uma peça.
// Tem teto de vértices e de tempo; roda em fatias para não travar o HUD. Sem three.js aqui (fácil de testar).

export const MAX_VERTICES = 1_500_000;
export const ORCAMENTO_MS = 4000;
export const MAX_PECAS = 200;

export interface OpcoesSeparar {
  maxVertices?: number;
  orcamentoMs?: number;
  maxPecas?: number;
  sinal?: AbortSignal;
  agora?: () => number;
}

/**
 * Recebe as posições de uma malha não indexada (9 números por triângulo) e devolve, para cada peça,
 * as posições dos seus triângulos. Devolve `null` se passar do teto ou do tempo (fica uma peça só).
 */
export async function separarPecas(posicoes: ArrayLike<number>, opcoes: OpcoesSeparar = {}): Promise<Float32Array[] | null> {
  const maxVertices = opcoes.maxVertices ?? MAX_VERTICES;
  const orcamento = opcoes.orcamentoMs ?? ORCAMENTO_MS;
  const maxPecas = opcoes.maxPecas ?? MAX_PECAS;
  const agora = opcoes.agora ?? (() => performance.now());
  const nVertices = Math.floor(posicoes.length / 3);
  const nTriangulos = Math.floor(nVertices / 3);
  if (nTriangulos < 2 || nVertices > maxVertices) return null;
  const inicio = agora();
  let fatia = agora();
  const pausa = async (): Promise<boolean> => {
    if (opcoes.sinal?.aborted || agora() - inicio > orcamento) return false;
    if (agora() - fatia > 40) {
      await new Promise((r) => setTimeout(r, 0));
      fatia = agora();
    }
    return !opcoes.sinal?.aborted;
  };

  // 1) vértices iguais (posição arredondada) recebem o mesmo número
  let minimo = Infinity;
  let maximo = -Infinity;
  for (let i = 0; i < nVertices * 3; i++) {
    const v = posicoes[i];
    if (v < minimo) minimo = v;
    if (v > maximo) maximo = v;
  }
  const passo = Math.max(maximo - minimo, 1e-9) * 1e-6;
  const ids = new Int32Array(nVertices);
  const vistos = new Map<string, number>();
  for (let v = 0; v < nVertices; v++) {
    if ((v & 8191) === 0 && !(await pausa())) return null;
    const chave = `${Math.round(posicoes[v * 3] / passo)},${Math.round(posicoes[v * 3 + 1] / passo)},${Math.round(posicoes[v * 3 + 2] / passo)}`;
    let id = vistos.get(chave);
    if (id === undefined) {
      id = vistos.size;
      vistos.set(chave, id);
    }
    ids[v] = id;
  }
  const nUnicos = vistos.size;
  vistos.clear();

  // 2) união de conjuntos pelos vértices de cada triângulo
  const pai = new Int32Array(nUnicos);
  for (let i = 0; i < nUnicos; i++) pai[i] = i;
  const raiz = (x: number): number => {
    while (pai[x] !== x) {
      pai[x] = pai[pai[x]];
      x = pai[x];
    }
    return x;
  };
  const unir = (a: number, b: number) => {
    const ra = raiz(a);
    const rb = raiz(b);
    if (ra !== rb) pai[ra] = rb;
  };
  for (let t = 0; t < nTriangulos; t++) {
    if ((t & 16383) === 0 && !(await pausa())) return null;
    unir(ids[t * 3], ids[t * 3 + 1]);
    unir(ids[t * 3], ids[t * 3 + 2]);
  }

  // 3) conta triângulos por peça
  const pecaDaRaiz = new Map<number, number>();
  const pecaDoTriangulo = new Int32Array(nTriangulos);
  const contagem: number[] = [];
  for (let t = 0; t < nTriangulos; t++) {
    const r = raiz(ids[t * 3]);
    let p = pecaDaRaiz.get(r);
    if (p === undefined) {
      p = contagem.length;
      pecaDaRaiz.set(r, p);
      contagem.push(0);
    }
    contagem[p]++;
    pecaDoTriangulo[t] = p;
  }
  if (contagem.length < 2) return [Float32Array.from(posicoes).slice(0, nTriangulos * 9)];

  // 4) peças demais: as maiores ficam separadas, o resto vira uma peça só
  let destino = contagem.map((_, i) => i);
  let nPecas = contagem.length;
  if (nPecas > maxPecas) {
    const ordem = contagem.map((_, i) => i).sort((a, b) => contagem[b] - contagem[a]);
    destino = new Array(nPecas).fill(maxPecas - 1);
    ordem.slice(0, maxPecas - 1).forEach((p, i) => (destino[p] = i));
    nPecas = maxPecas;
  }
  const tamanhos = new Array(nPecas).fill(0);
  contagem.forEach((c, p) => (tamanhos[destino[p]] += c));
  const saidas = tamanhos.map((n) => new Float32Array(n * 9));
  const cursores = new Array(nPecas).fill(0);
  for (let t = 0; t < nTriangulos; t++) {
    const d = destino[pecaDoTriangulo[t]];
    const saida = saidas[d];
    let c = cursores[d];
    for (let k = 0; k < 9; k++) saida[c++] = posicoes[t * 9 + k];
    cursores[d] = c;
  }
  return saidas;
}

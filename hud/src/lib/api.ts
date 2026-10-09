// Chave de acesso e chamadas à API da Sexta-Feira.

const CHAVE_TOKEN = "sexta.token";
let tokenMemoria: string | null = null;

function lerStorage(chave: string): string | null {
  try {
    return window.localStorage.getItem(chave);
  } catch {
    return null;
  }
}

function gravarStorage(chave: string, valor: string | null): void {
  try {
    if (valor === null) window.localStorage.removeItem(chave);
    else window.localStorage.setItem(chave, valor);
  } catch {
    /* navegação privada: fica só na memória */
  }
}

export function token(): string | null {
  return tokenMemoria ?? lerStorage(CHAVE_TOKEN);
}

export function salvarToken(valor: string | null): void {
  tokenMemoria = valor;
  gravarStorage(CHAVE_TOKEN, valor);
}

/** Pega o token da URL (#t=...) que a própria Sexta abre, e limpa a barra de endereço. */
export function capturarTokenDaUrl(): void {
  const hash = new URLSearchParams(window.location.hash.replace(/^#/, ""));
  const t = hash.get("t");
  if (t) {
    salvarToken(t);
    history.replaceState(null, "", window.location.pathname + window.location.search);
  }
}

export function codigoDePareamentoNaUrl(): string | null {
  return new URLSearchParams(window.location.search).get("pareamento");
}

export function limparCodigoDaUrl(): void {
  history.replaceState(null, "", window.location.pathname);
}

export class ErroApi extends Error {
  constructor(
    public status: number,
    mensagem: string,
  ) {
    super(mensagem);
  }
}

export async function api<T = unknown>(caminho: string, opcoes: RequestInit & { json?: unknown } = {}): Promise<T> {
  const cabecalhos = new Headers(opcoes.headers);
  const t = token();
  if (t) cabecalhos.set("Authorization", `Bearer ${t}`);
  let corpo = opcoes.body;
  if (opcoes.json !== undefined) {
    cabecalhos.set("Content-Type", "application/json");
    corpo = JSON.stringify(opcoes.json);
  }
  const resposta = await fetch(caminho, { ...opcoes, headers: cabecalhos, body: corpo });
  if (!resposta.ok) {
    let mensagem = `Erro ${resposta.status}`;
    try {
      const dados = await resposta.json();
      mensagem = dados.erro ?? dados.detail ?? mensagem;
    } catch {
      /* resposta sem JSON */
    }
    throw new ErroApi(resposta.status, mensagem);
  }
  const tipo = resposta.headers.get("content-type") ?? "";
  return (tipo.includes("application/json") ? resposta.json() : resposta.text()) as Promise<T>;
}

/** URL com o token na query (para <img>, <audio> e MJPEG, que não mandam cabeçalhos). */
export function comToken(caminho: string): string {
  const t = token();
  if (!t) return caminho;
  return `${caminho}${caminho.includes("?") ? "&" : "?"}token=${encodeURIComponent(t)}`;
}

export function nomeDoAparelho(): string {
  const ua = navigator.userAgent;
  if (/iPhone/.test(ua)) return "iPhone";
  if (/iPad/.test(ua)) return "iPad";
  const android = ua.match(/Android[^;]*;\s*([^;)]+?)(?:\sBuild|\))/);
  if (android?.[1]) return android[1].trim().slice(0, 40);
  if (/Android/.test(ua)) return "Android";
  return "Celular";
}

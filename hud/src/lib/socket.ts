import { ErroApi, api, token } from "./api";
import { aplicarEvento, useHud } from "./store";

type Ouvinte = (evento: any) => void;

class Conexao {
  private ws: WebSocket | null = null;
  private tentativas = 0;
  private ouvintes = new Set<Ouvinte>();
  private querMaos = false;
  private parado = false;

  conectar(): void {
    if (useHud.getState().semAcesso) return;
    this.parado = false;
    if (this.ws && this.ws.readyState <= WebSocket.OPEN) return;
    const t = token();
    if (!t) {
      useHud.setState({ semAcesso: true });
      return;
    }
    const protocolo = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${protocolo}://${location.host}/ws?token=${encodeURIComponent(t)}`);
    this.ws = ws;
    let abriu = false;
    ws.onopen = () => {
      abriu = true;
      this.tentativas = 0;
      if (this.querMaos) this.enviar({ tipo: "maos", ligar: true });
    };
    ws.onmessage = (m) => {
      let evento: any;
      try {
        evento = JSON.parse(m.data);
      } catch {
        return;
      }
      aplicarEvento(evento);
      this.ouvintes.forEach((o) => o(evento));
    };
    ws.onclose = (fechamento) => {
      if (this.ws !== ws) return; // conexão antiga (já substituída)
      useHud.setState({ conectado: false });
      if (fechamento.code === 4401) {
        useHud.setState({ semAcesso: true });
        return;
      }
      if (!abriu) {
        // a conexão nem abriu: confere se a chave ainda vale (ex.: celular removido no PC)
        api("/api/estado").catch((erro) => {
          if (erro instanceof ErroApi && erro.status === 401) {
            this.parado = true;
            useHud.setState({ semAcesso: true });
          }
        });
      }
      if (this.parado) return;
      const espera = Math.min(8000, 600 * 2 ** this.tentativas++);
      window.setTimeout(() => this.conectar(), espera);
    };
  }

  enviar(mensagem: object): void {
    if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify(mensagem));
  }

  /** Avisa o servidor se este HUD quer receber os pontos das mãos. */
  definirMaos(ligar: boolean): void {
    this.querMaos = ligar;
    this.enviar({ tipo: "maos", ligar });
  }

  ouvir(funcao: Ouvinte): () => void {
    this.ouvintes.add(funcao);
    return () => this.ouvintes.delete(funcao);
  }

  parar(): void {
    this.parado = true;
    const ws = this.ws;
    this.ws = null;
    ws?.close();
  }
}

export const conexao = new Conexao();

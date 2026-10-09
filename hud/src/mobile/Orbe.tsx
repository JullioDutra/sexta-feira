// Versão leve do núcleo para o celular (canvas 2D).
import { useEffect, useRef } from "react";
import { tempoReal, useHud } from "../lib/store";

export default function Orbe({ tamanho = 150 }: { tamanho?: number }) {
  const ref = useRef<HTMLCanvasElement>(null);
  const estado = useHud((s) => s.estado);
  const bloqueada = useHud((s) => s.bloqueio.bloqueada);
  const conectado = useHud((s) => s.conectado);
  const estadoRef = useRef({ estado, bloqueada, conectado });
  estadoRef.current = { estado, bloqueada, conectado };

  useEffect(() => {
    const canvas = ref.current!;
    const ctx = canvas.getContext("2d")!;
    const dpr = window.devicePixelRatio || 1;
    canvas.width = tamanho * dpr;
    canvas.height = tamanho * dpr;
    ctx.scale(dpr, dpr);
    const pontos = Array.from({ length: 160 }, () => ({ a: Math.random() * Math.PI * 2, r: Math.random(), v: 0.2 + Math.random() * 0.8 }));
    let nivel = 0;
    let quadro = 0;
    const c = tamanho / 2;
    const desenhar = (t: number) => {
      quadro = requestAnimationFrame(desenhar);
      const { estado: e, bloqueada: b, conectado: on } = estadoRef.current;
      const luz = b ? "255,93,98" : !on ? "95,124,147" : "255,181,71";
      const alvo = e === "ouvindo" ? tempoReal.nivelMic : e === "falando" ? tempoReal.nivelFala : 0;
      nivel += (alvo - nivel) * 0.2;
      const velocidade = e === "pensando" ? 3 : e === "ouvindo" ? 1.4 : 0.6;
      const tempo = t / 1000;
      ctx.clearRect(0, 0, tamanho, tamanho);
      const brilho = ctx.createRadialGradient(c, c, 0, c, c, c);
      brilho.addColorStop(0, `rgba(${luz},${0.35 + nivel * 0.4})`);
      brilho.addColorStop(0.35, `rgba(${luz},0.08)`);
      brilho.addColorStop(1, "rgba(0,0,0,0)");
      ctx.fillStyle = brilho;
      ctx.fillRect(0, 0, tamanho, tamanho);
      const raioBase = tamanho * (0.22 + nivel * 0.06 + (e === "ouvindo" ? 0.03 : 0));
      for (const p of pontos) {
        const ang = p.a + tempo * 0.4 * p.v * velocidade;
        const r = raioBase * (0.35 + p.r * 0.65) * (1 + Math.sin(tempo * 2 + p.a * 3) * (0.04 + nivel * 0.25));
        ctx.fillStyle = `rgba(${luz},${0.35 + p.r * 0.6})`;
        ctx.fillRect(c + Math.cos(ang) * r, c + Math.sin(ang) * r * 0.92, 1.4, 1.4);
      }
      const aneis = [
        { r: 0.34, larg: 1.2, arco: 1.8, giro: 0.5 },
        { r: 0.41, larg: 1, arco: 0.9, giro: -0.35 },
        { r: 0.47, larg: 0.8, arco: 4.6, giro: 0.15 },
      ];
      aneis.forEach((anel, i) => {
        ctx.strokeStyle = `rgba(${luz},${0.75 - i * 0.18})`;
        ctx.lineWidth = anel.larg;
        const inicio = tempo * anel.giro * velocidade;
        for (let k = 0; k < (i === 2 ? 1 : 3); k++) {
          ctx.beginPath();
          ctx.arc(c, c, tamanho * anel.r * (1 + nivel * 0.08), inicio + (k * Math.PI * 2) / 3, inicio + (k * Math.PI * 2) / 3 + anel.arco);
          ctx.stroke();
        }
      });
    };
    quadro = requestAnimationFrame(desenhar);
    return () => cancelAnimationFrame(quadro);
  }, [tamanho]);

  return <canvas ref={ref} style={{ width: tamanho, height: tamanho }} aria-hidden="true" />;
}

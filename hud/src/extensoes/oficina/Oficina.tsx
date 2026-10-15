// Holograma "Oficina": o modelo 3D em luz (material translúcido + arestas), girando devagar.
// Arrastar (mouse ou pinça da mão) gira, a rodinha e os botões +/- aproximam, "Explodir" afasta as peças do centro.
// Tudo que é criado aqui (geometrias, materiais, renderizador) é liberado ao fechar.
import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { api } from "../../lib/api";
import { carregarModelo } from "./carregar";
import { EVENTO_COMANDO, corDaLuz, type AcaoOficina, type DadosOficina } from "./tipos";

const MAX_TRIANGULOS_ARESTAS = 400_000; // acima disso, arestas pesam demais: fica só o material
const ANGULO_ARESTAS = 28;
const AFASTAMENTO = 1.25; // quanto cada peça se afasta (vezes a distância do centro) com tudo explodido

interface Controle {
  rotY: number;
  rotX: number;
  vy: number;
  vx: number;
  auto: boolean;
  zoom: number;
  explosao: number;
  alvoExplosao: number;
  ultimoToque: number;
}

interface Props {
  dados: DadosOficina;
  largura?: number;
  altura?: number;
}

export default function Oficina({ dados, largura = 480, altura = 400 }: Props) {
  const area = useRef<HTMLDivElement>(null);
  const tela = useRef<HTMLDivElement>(null);
  const controle = useRef<Controle>({ rotY: 0.6, rotX: 0.35, vy: 0, vx: 0, auto: true, zoom: 1, explosao: 0, alvoExplosao: 0, ultimoToque: 0 });
  const [fase, setFase] = useState<"carregando" | "pronto" | "erro">("carregando");
  const [erro, setErro] = useState("");
  const [pecas, setPecas] = useState(0);
  const [triangulos, setTriangulos] = useState(0);
  const [auto, setAuto] = useState(true);
  const [explosao, setExplosao] = useState(0);
  const [aviso, setAviso] = useState("");

  // cena three.js: criada uma vez por modelo, liberada ao trocar ou fechar
  useEffect(() => {
    const el = tela.current;
    if (!el || !dados?.url || !dados.formato) return;
    const sinal = new AbortController();
    const c = controle.current;
    c.explosao = c.alvoExplosao = 0;
    setExplosao(0);
    setFase("carregando");
    setErro("");
    setPecas(0);

    let renderizador: THREE.WebGLRenderer;
    try {
      renderizador = new THREE.WebGLRenderer({ alpha: true, antialias: true });
    } catch {
      setFase("erro");
      setErro("Este navegador não conseguiu iniciar o 3D (WebGL).");
      return;
    }
    renderizador.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderizador.setClearColor(0x000000, 0);
    el.appendChild(renderizador.domElement);
    renderizador.domElement.style.display = "block";

    const cena = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(38, 1, 0.01, 100);
    const cor = new THREE.Color(corDaLuz());
    cena.add(new THREE.HemisphereLight(0xffffff, 0x223344, 1.1));
    const luz = new THREE.DirectionalLight(0xffffff, 0.9);
    luz.position.set(2, 3, 4);
    cena.add(luz);
    const pivo = new THREE.Group();
    cena.add(pivo);

    const material = new THREE.MeshPhongMaterial({
      color: new THREE.Color(0x0a1a26),
      emissive: cor,
      emissiveIntensity: 0.32,
      specular: cor,
      shininess: 40,
      transparent: true,
      opacity: 0.32,
      side: THREE.DoubleSide,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
    });
    const materialLinhas = new THREE.LineBasicMaterial({ color: cor, transparent: true, opacity: 0.75, blending: THREE.AdditiveBlending, depthWrite: false });
    const descartaveis: { dispose: () => void }[] = [material, materialLinhas];
    const partes: { grupo: THREE.Group; direcao: THREE.Vector3 }[] = [];
    let raio = 1;

    const redimensionar = () => {
      const l = el.clientWidth || largura;
      const a = el.clientHeight || altura;
      renderizador.setSize(l, a, false);
      renderizador.domElement.style.width = `${l}px`;
      renderizador.domElement.style.height = `${a}px`;
      camera.aspect = l / a;
      camera.updateProjectionMatrix();
    };
    redimensionar();
    const observador = new ResizeObserver(redimensionar);
    observador.observe(el);

    carregarModelo(dados.url, dados.formato, sinal.signal)
      .then(({ pecas: geometrias, triangulos: total }) => {
        if (sinal.signal.aborted) {
          geometrias.forEach((g) => g.dispose());
          return;
        }
        // centro e tamanho do modelo inteiro
        const caixa = new THREE.Box3();
        for (const g of geometrias) {
          g.computeBoundingBox();
          caixa.union(g.boundingBox!);
        }
        const centro = caixa.getCenter(new THREE.Vector3());
        const tamanho = caixa.getSize(new THREE.Vector3());
        const escala = 2 / Math.max(tamanho.x, tamanho.y, tamanho.z, 1e-6);
        const comArestas = total <= MAX_TRIANGULOS_ARESTAS;
        for (const g of geometrias) {
          g.translate(-centro.x, -centro.y, -centro.z);
          g.scale(escala, escala, escala);
          g.computeBoundingBox();
          const grupo = new THREE.Group();
          grupo.add(new THREE.Mesh(g, material));
          descartaveis.push(g);
          if (comArestas) {
            const arestas = new THREE.EdgesGeometry(g, ANGULO_ARESTAS);
            descartaveis.push(arestas);
            grupo.add(new THREE.LineSegments(arestas, materialLinhas));
          }
          pivo.add(grupo);
          partes.push({ grupo, direcao: g.boundingBox!.getCenter(new THREE.Vector3()) });
        }
        // peças no centro exato (ex.: eixo) também se afastam um pouco, para cima
        for (const p of partes) if (p.direcao.lengthSq() < 1e-6 && partes.length > 1) p.direcao.set(0, 0.3, 0);
        raio = Math.sqrt(3) * 1.02;
        setPecas(partes.length);
        setTriangulos(Math.round(total));
        setFase("pronto");
        if (dados.id) api("/api/oficina/pecas", { method: "POST", json: { id: dados.id, pecas: partes.length } }).catch(() => {});
      })
      .catch((e: Error) => {
        if (sinal.signal.aborted) return;
        setFase("erro");
        setErro(e?.message || "Não consegui abrir esse modelo.");
      });

    let quadro = 0;
    let anterior = performance.now();
    const desenhar = (agora: number) => {
      quadro = requestAnimationFrame(desenhar);
      const dt = Math.min(0.1, (agora - anterior) / 1000);
      anterior = agora;
      const ocioso = agora - c.ultimoToque > 1500;
      c.rotY += c.vy * dt + (c.auto && ocioso ? dt * 0.35 : 0);
      c.rotX = Math.max(-1.4, Math.min(1.4, c.rotX + c.vx * dt));
      c.vy *= Math.pow(0.05, dt);
      c.vx *= Math.pow(0.05, dt);
      pivo.rotation.set(c.rotX, c.rotY, 0);
      c.explosao += (c.alvoExplosao - c.explosao) * (1 - Math.pow(0.02, dt));
      for (const p of partes) p.grupo.position.copy(p.direcao).multiplyScalar(c.explosao * AFASTAMENTO);
      const distancia = (raio * (1 + c.explosao * AFASTAMENTO)) / Math.sin((camera.fov * Math.PI) / 360) / c.zoom;
      camera.position.set(0, 0, distancia);
      camera.near = distancia / 100;
      camera.far = distancia * 10;
      camera.updateProjectionMatrix();
      renderizador.render(cena, camera);
    };
    quadro = requestAnimationFrame(desenhar);

    return () => {
      sinal.abort();
      cancelAnimationFrame(quadro);
      observador.disconnect();
      for (const d of descartaveis) d.dispose();
      renderizador.dispose();
      renderizador.forceContextLoss();
      renderizador.domElement.remove();
    };
  }, [dados?.url, dados?.formato, dados?.id, largura, altura]);

  // pinça da mão (evento "girar" do Palco) e rodinha do mouse (sem ampliar o holograma inteiro)
  useEffect(() => {
    const el = area.current;
    if (!el) return;
    const aoGirar = (e: Event) => {
      const { dx, dy } = (e as CustomEvent<{ dx: number; dy: number }>).detail;
      girar(controle.current, dx, dy, 0.016);
    };
    const aoRolar = (e: WheelEvent) => {
      e.preventDefault();
      e.stopPropagation();
      const c = controle.current;
      c.zoom = Math.max(0.4, Math.min(4, c.zoom * Math.exp(-e.deltaY * 0.0015)));
    };
    el.addEventListener("girar", aoGirar);
    el.addEventListener("wheel", aoRolar, { passive: false });
    return () => {
      el.removeEventListener("girar", aoGirar);
      el.removeEventListener("wheel", aoRolar);
    };
  }, []);

  // comandos de voz
  useEffect(() => {
    const aoComando = (e: Event) => {
      const { acao } = (e as CustomEvent<{ acao: AcaoOficina }>).detail;
      if (acao === "explodir" || acao === "juntar") mudarExplosao(acao === "explodir" ? 1 : 0);
      else alternarGiro(acao === "girar");
    };
    window.addEventListener(EVENTO_COMANDO, aoComando);
    return () => window.removeEventListener(EVENTO_COMANDO, aoComando);
  });

  useEffect(() => {
    if (!aviso) return;
    const t = setTimeout(() => setAviso(""), 3000);
    return () => clearTimeout(t);
  }, [aviso]);

  const mudarExplosao = (valor: number) => {
    if (valor > 0 && fase === "pronto" && pecas <= 1) {
      setAviso("Esse modelo tem uma peça só.");
      return;
    }
    controle.current.alvoExplosao = valor;
    setExplosao(valor);
  };
  const alternarGiro = (ligar: boolean) => {
    controle.current.auto = ligar;
    setAuto(ligar);
  };
  const aproximar = (fator: number) => {
    const c = controle.current;
    c.zoom = Math.max(0.4, Math.min(4, c.zoom * fator));
  };

  const arrastando = useRef<{ x: number; y: number; t: number } | null>(null);
  const semModelo = !dados?.url;

  return (
    <div style={{ width: largura }} className="max-w-full">
      <div
        ref={area}
        data-girar
        className="relative cursor-grab active:cursor-grabbing touch-none overflow-hidden"
        style={{ height: altura }}
        onPointerDown={(e) => {
          e.stopPropagation();
          (e.target as HTMLElement).setPointerCapture(e.pointerId);
          arrastando.current = { x: e.clientX, y: e.clientY, t: performance.now() };
        }}
        onPointerMove={(e) => {
          const a = arrastando.current;
          if (!a) return;
          const dt = Math.max(1, performance.now() - a.t) / 1000;
          girar(controle.current, e.clientX - a.x, e.clientY - a.y, dt);
          arrastando.current = { x: e.clientX, y: e.clientY, t: performance.now() };
        }}
        onPointerUp={() => (arrastando.current = null)}
        onPointerCancel={() => (arrastando.current = null)}
      >
        <Grade />
        <div ref={tela} className="absolute inset-0" />
        {semModelo && (
          <p className="absolute inset-0 flex items-center justify-center px-8 text-center text-sm text-aco">
            Bancada vazia. Diga, por exemplo: “abre o modelo do capacete na oficina”.
          </p>
        )}
        {!semModelo && fase === "carregando" && (
          <p className="absolute inset-0 flex items-center justify-center text-sm text-aco animate-pulse">Projetando {dados.nome}…</p>
        )}
        {fase === "erro" && <p className="absolute inset-0 flex items-center justify-center px-8 text-center text-sm text-coral">{erro}</p>}
        {aviso && (
          <p role="status" className="absolute left-1/2 top-3 -translate-x-1/2 rounded border border-[var(--luz)]/40 bg-black/60 px-3 py-1 text-xs text-gelo">
            {aviso}
          </p>
        )}
      </div>
      {!semModelo && (
        <div className="mt-2 space-y-2">
          <div className="flex items-center gap-2 text-xs">
            <Botao onClick={() => mudarExplosao(1)} ativo={explosao > 0.5}>
              Explodir
            </Botao>
            <Botao onClick={() => mudarExplosao(0)} ativo={explosao <= 0.5}>
              Juntar
            </Botao>
            <input
              type="range"
              min={0}
              max={1}
              step={0.01}
              value={explosao}
              aria-label="Afastamento das peças"
              disabled={fase !== "pronto" || pecas <= 1}
              onChange={(e) => mudarExplosao(Number(e.target.value))}
              className="min-w-0 flex-1 accent-[var(--luz)]"
            />
            <Botao onClick={() => aproximar(1 / 1.25)} rotulo="Afastar">
              −
            </Botao>
            <Botao onClick={() => aproximar(1.25)} rotulo="Aproximar">
              +
            </Botao>
            <Botao onClick={() => alternarGiro(!auto)} ativo={auto} rotulo={auto ? "Parar de girar" : "Girar"}>
              ⟳
            </Botao>
          </div>
          <p className="flex justify-between gap-3 text-[11px] text-aco">
            <span className="truncate" title={dados.nome}>
              {dados.nome} · {dados.formato?.toUpperCase()} · {dados.tamanho}
            </span>
            {fase === "pronto" && (
              <span className="shrink-0">
                {pecas} {pecas === 1 ? "peça" : "peças"} · {triangulos.toLocaleString("pt-BR")} triângulos
              </span>
            )}
          </p>
        </div>
      )}
    </div>
  );
}

function girar(c: Controle, dx: number, dy: number, dt: number) {
  c.rotY += dx * 0.009;
  c.rotX += dy * 0.007;
  c.vy = (dx * 0.009) / Math.max(dt, 0.016);
  c.vx = (dy * 0.007) / Math.max(dt, 0.016);
  c.ultimoToque = performance.now();
}

function Botao({ children, onClick, ativo, rotulo }: { children: React.ReactNode; onClick: () => void; ativo?: boolean; rotulo?: string }) {
  return (
    <button
      type="button"
      data-clicavel
      onClick={onClick}
      aria-label={rotulo}
      title={rotulo}
      className={`shrink-0 rounded border px-2 py-0.5 transition-colors ${
        ativo ? "border-[var(--luz)] text-[var(--luz)]" : "border-[var(--luz)]/30 text-aco hover:text-gelo"
      }`}
    >
      {children}
    </button>
  );
}

/** Grade de bancada ao fundo (só CSS: não pesa no WebGL). */
function Grade() {
  return (
    <div
      aria-hidden="true"
      className="pointer-events-none absolute inset-x-0 bottom-0 h-1/2"
      style={{
        backgroundImage:
          "linear-gradient(rgb(var(--luz-rgb) / 0.12) 1px, transparent 1px), linear-gradient(90deg, rgb(var(--luz-rgb) / 0.12) 1px, transparent 1px)",
        backgroundSize: "28px 28px",
        maskImage: "linear-gradient(to top, black, transparent)",
        WebkitMaskImage: "linear-gradient(to top, black, transparent)",
        transform: "perspective(300px) rotateX(55deg)",
        transformOrigin: "bottom",
      }}
    />
  );
}

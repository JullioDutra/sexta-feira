// O núcleo da Sexta-Feira: um "sol de filamentos" que reage ao estado e à voz.
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { useMemo, useRef } from "react";
import * as THREE from "three";
import { tempoReal, useHud } from "../lib/store";

const COR = {
  ambar: new THREE.Color("#ffb547"),
  brasa: new THREE.Color("#ff7a2f"),
  gelo: new THREE.Color("#d8eeff"),
  coral: new THREE.Color("#ff5d62"),
  menta: new THREE.Color("#7cf2b8"),
  ciano: new THREE.Color("#57d6ff"),
  azul: new THREE.Color("#2f9bff"),
};

const VERTICE_PARTICULAS = /* glsl */ `
  uniform float uTempo;
  uniform float uNivel;
  uniform float uAbertura;
  uniform float uPixel;
  attribute float aSemente;
  varying float vAlfa;
  varying float vSemente;
  void main() {
    vec3 p = position;
    float onda = sin(p.x * 4.1 + uTempo * 1.3 + aSemente * 6.28) * sin(p.y * 5.3 - uTempo * 1.1) * sin(p.z * 4.6 + uTempo * 0.8);
    float respiro = 1.0 + onda * (0.035 + uNivel * 0.32) + uAbertura * 0.22 + sin(uTempo * 0.9) * 0.012;
    p *= respiro;
    vec4 mv = modelViewMatrix * vec4(p, 1.0);
    gl_Position = projectionMatrix * mv;
    gl_PointSize = (1.3 + aSemente * 1.9 + uNivel * 1.6) * uPixel * (6.0 / -mv.z);
    float frente = clamp(normalize(p).z * 0.5 + 0.5, 0.0, 1.0);
    vAlfa = 0.18 + 0.82 * frente;
    vSemente = aSemente;
  }
`;

const FRAGMENTO_PARTICULAS = /* glsl */ `
  uniform vec3 uCor;
  uniform vec3 uCorDetalhe;
  uniform float uBrilho;
  varying float vAlfa;
  varying float vSemente;
  void main() {
    vec2 c = gl_PointCoord - 0.5;
    float d = length(c);
    if (d > 0.5) discard;
    float a = smoothstep(0.5, 0.0, d);
    vec3 cor = mix(uCor, uCorDetalhe, step(0.93, vSemente));
    gl_FragColor = vec4(cor, a * vAlfa * uBrilho);
  }
`;

function texturaBrilho(): THREE.Texture {
  const tela = document.createElement("canvas");
  tela.width = tela.height = 128;
  const ctx = tela.getContext("2d")!;
  const g = ctx.createRadialGradient(64, 64, 0, 64, 64, 64);
  g.addColorStop(0, "rgba(255,255,255,1)");
  g.addColorStop(0.18, "rgba(255,255,255,0.55)");
  g.addColorStop(0.45, "rgba(255,255,255,0.12)");
  g.addColorStop(1, "rgba(255,255,255,0)");
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, 128, 128);
  const t = new THREE.CanvasTexture(tela);
  t.colorSpace = THREE.SRGBColorSpace;
  return t;
}

function esferaFibonacci(n: number, raio: number) {
  const posicoes = new Float32Array(n * 3);
  const sementes = new Float32Array(n);
  const ouro = Math.PI * (3 - Math.sqrt(5));
  for (let i = 0; i < n; i++) {
    const y = 1 - (i / (n - 1)) * 2;
    const r = Math.sqrt(1 - y * y);
    const theta = ouro * i;
    const jitter = 1 + (Math.random() - 0.5) * 0.06;
    posicoes[i * 3] = Math.cos(theta) * r * raio * jitter;
    posicoes[i * 3 + 1] = y * raio * jitter;
    posicoes[i * 3 + 2] = Math.sin(theta) * r * raio * jitter;
    sementes[i] = Math.random();
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.BufferAttribute(posicoes, 3));
  g.setAttribute("aSemente", new THREE.BufferAttribute(sementes, 1));
  return g;
}

function circulo(raio: number, inicio = 0, fim = Math.PI * 2, segmentos = 256) {
  const pts: THREE.Vector3[] = [];
  for (let i = 0; i <= segmentos; i++) {
    const a = inicio + ((fim - inicio) * i) / segmentos;
    pts.push(new THREE.Vector3(Math.cos(a) * raio, Math.sin(a) * raio, 0));
  }
  return new THREE.BufferGeometry().setFromPoints(pts);
}

function marcas(raio: number, n: number, curta: number, longa: number) {
  const pts: THREE.Vector3[] = [];
  for (let i = 0; i < n; i++) {
    const a = (i / n) * Math.PI * 2;
    const l = i % 10 === 0 ? longa : curta;
    pts.push(new THREE.Vector3(Math.cos(a) * raio, Math.sin(a) * raio, 0));
    pts.push(new THREE.Vector3(Math.cos(a) * (raio + l), Math.sin(a) * (raio + l), 0));
  }
  return new THREE.BufferGeometry().setFromPoints(pts);
}

function Linha({ geometria, cor, opacidade, traco = 0, vao = 0 }: { geometria: THREE.BufferGeometry; cor: THREE.Color; opacidade: number; traco?: number; vao?: number }) {
  const linha = useMemo(() => {
    const comum = { color: cor.clone(), transparent: true, opacity: opacidade, blending: THREE.AdditiveBlending, depthWrite: false };
    const material = traco ? new THREE.LineDashedMaterial({ ...comum, dashSize: traco, gapSize: vao }) : new THREE.LineBasicMaterial(comum);
    const l = new THREE.Line(geometria, material);
    if (traco) l.computeLineDistances();
    return l;
  }, [geometria, cor, opacidade, traco, vao]);
  return <primitive object={linha} />;
}

interface Alvos {
  cor: THREE.Color;
  detalhe: THREE.Color;
  velocidade: number;
  abertura: number;
  brilho: number;
  cometa: number;
  varredura: number;
}

function alvosPara(estado: string, bloqueada: boolean, verificando: string | null, tema: string): Alvos {
  const ciano = tema === "jarvis";
  const base = ciano ? COR.ciano : COR.ambar;
  const quente = ciano ? COR.azul : COR.brasa;
  if (verificando === "ok") return { cor: COR.menta, detalhe: COR.gelo, velocidade: 1.5, abertura: 0.25, brilho: 1.3, cometa: 0, varredura: 0 };
  if (bloqueada || estado === "verificando")
    return { cor: COR.coral, detalhe: base, velocidade: 0.6, abertura: 0, brilho: 0.85, cometa: 0, varredura: 1 };
  switch (estado) {
    case "ouvindo":
      return { cor: base, detalhe: COR.gelo, velocidade: 1.2, abertura: 0.32, brilho: 1.25, cometa: 0, varredura: 0 };
    case "pensando":
      return { cor: quente, detalhe: base, velocidade: 4.5, abertura: 0.08, brilho: 1.1, cometa: 1, varredura: 0 };
    case "falando":
      return { cor: base, detalhe: COR.gelo, velocidade: 1.6, abertura: 0.05, brilho: 1.2, cometa: 0, varredura: 0 };
    case "iniciando":
      return { cor: base, detalhe: COR.gelo, velocidade: 0.4, abertura: -0.2, brilho: 0.5, cometa: 0, varredura: 0 };
    default:
      return { cor: base, detalhe: COR.gelo, velocidade: 0.5, abertura: 0, brilho: 0.85, cometa: 0, varredura: 0 };
  }
}

function Sol({ deslocamentoY }: { deslocamentoY: number }) {
  const estado = useHud((s) => s.estado);
  const bloqueada = useHud((s) => s.bloqueio.bloqueada);
  const verificacao = useHud((s) => s.verificacao?.fase ?? null);
  const tema = useHud((s) => s.prefs?.tema ?? "sexta");
  const { gl } = useThree();

  const grupo = useRef<THREE.Group>(null);
  const aneis = useRef<THREE.Group[]>([]);
  const cometa = useRef<THREE.Sprite>(null);
  const brilho = useRef<THREE.Sprite>(null);
  const centro = useRef<THREE.Sprite>(null);
  const varredura = useRef<THREE.Mesh>(null);
  const atual = useRef({ nivel: 0, abertura: 0, velocidade: 0.5, brilho: 0.8, cometa: 0, varredura: 0, angulo: [0, 0, 0, 0, 0] });

  const textura = useMemo(texturaBrilho, []);
  const geometria = useMemo(() => esferaFibonacci(2600, 0.62), []);
  const material = useMemo(
    () =>
      new THREE.ShaderMaterial({
        vertexShader: VERTICE_PARTICULAS,
        fragmentShader: FRAGMENTO_PARTICULAS,
        transparent: true,
        depthWrite: false,
        blending: THREE.AdditiveBlending,
        uniforms: {
          uTempo: { value: 0 },
          uNivel: { value: 0 },
          uAbertura: { value: 0 },
          uPixel: { value: Math.min(2, window.devicePixelRatio || 1) },
          uCor: { value: COR.ambar.clone() },
          uCorDetalhe: { value: COR.gelo.clone() },
          uBrilho: { value: 0.9 },
        },
      }),
    [],
  );
  const geo = useMemo(
    () => ({
      a: circulo(0.95),
      b1: circulo(1.12, 0.2, 1.4),
      b2: circulo(1.12, 2.3, 3.5),
      b3: circulo(1.12, 4.4, 5.6),
      c: marcas(1.33, 120, 0.035, 0.08),
      d: circulo(0.8),
      e1: circulo(1.62, 0.6, 1.5),
      e2: circulo(1.62, 3.7, 4.6),
    }),
    [],
  );
  const corLinha = useMemo(() => COR.ambar.clone(), []);
  const marcasLinha = useMemo(
    () =>
      new THREE.LineSegments(
        geo.c,
        new THREE.LineBasicMaterial({ color: COR.ambar.clone(), transparent: true, opacity: 0.4, blending: THREE.AdditiveBlending, depthWrite: false }),
      ),
    [geo],
  );

  useFrame((estadoFrame, delta) => {
    const t = estadoFrame.clock.elapsedTime;
    const alvo = alvosPara(estado, bloqueada, verificacao, tema);
    const a = atual.current;
    const k = 1 - Math.pow(0.002, delta);
    const nivelBruto = estado === "ouvindo" ? tempoReal.nivelMic : estado === "falando" ? tempoReal.nivelFala : 0;
    a.nivel += (nivelBruto - a.nivel) * Math.min(1, delta * 14);
    a.abertura += (alvo.abertura - a.abertura) * k;
    a.velocidade += (alvo.velocidade - a.velocidade) * k;
    a.brilho += (alvo.brilho - a.brilho) * k;
    a.cometa += (alvo.cometa - a.cometa) * k;
    a.varredura += (alvo.varredura - a.varredura) * k;

    const u = material.uniforms;
    u.uTempo.value = t;
    u.uNivel.value = a.nivel;
    u.uAbertura.value = a.abertura;
    u.uBrilho.value = a.brilho;
    (u.uCor.value as THREE.Color).lerp(alvo.cor, k);
    (u.uCorDetalhe.value as THREE.Color).lerp(alvo.detalhe, k);
    corLinha.lerp(alvo.cor, k);

    const sentidos = [0.25, -0.18, 0.08, 0.5, -0.06];
    aneis.current.forEach((anel, i) => {
      if (!anel) return;
      a.angulo[i] += delta * sentidos[i] * a.velocidade;
      anel.rotation.z = a.angulo[i];
      const escala = 1 + a.abertura * (0.35 + i * 0.08) + (i === 0 ? a.nivel * 0.25 : 0);
      anel.scale.setScalar(escala);
      anel.children.forEach((filho) => {
        const m = (filho as THREE.Line).material as THREE.LineBasicMaterial;
        m.color.copy(corLinha);
      });
    });
    if (grupo.current) {
      grupo.current.rotation.y = Math.sin(t * 0.21) * 0.18;
      grupo.current.rotation.x = Math.sin(t * 0.17) * 0.08;
    }
    if (cometa.current) {
      const ang = t * 3.2;
      cometa.current.position.set(Math.cos(ang) * 0.8, Math.sin(ang) * 0.8 * Math.cos(1.15), Math.sin(ang) * 0.8 * Math.sin(1.15));
      (cometa.current.material as THREE.SpriteMaterial).opacity = a.cometa;
      (cometa.current.material as THREE.SpriteMaterial).color.copy(corLinha);
    }
    if (brilho.current) {
      const m = brilho.current.material as THREE.SpriteMaterial;
      m.color.copy(corLinha);
      m.opacity = 0.22 + a.nivel * 0.35 + a.abertura * 0.2;
      brilho.current.scale.setScalar(2.6 + a.nivel * 0.8 + a.abertura);
    }
    if (centro.current) {
      const m = centro.current.material as THREE.SpriteMaterial;
      m.opacity = 0.55 + a.nivel * 0.45;
      centro.current.scale.setScalar(0.55 + a.nivel * 0.35 + Math.sin(t * 2.2) * 0.02);
    }
    if (varredura.current) {
      varredura.current.position.y = Math.sin(t * 1.4) * 0.72;
      (varredura.current.material as THREE.MeshBasicMaterial).opacity = a.varredura * 0.55;
      (varredura.current.material as THREE.MeshBasicMaterial).color.copy(corLinha);
    }
    gl.setClearAlpha(0);
  });

  const registrar = (i: number) => (g: THREE.Group | null) => {
    if (g) aneis.current[i] = g;
  };

  return (
    <group position={[0, deslocamentoY, 0]}>
      <sprite ref={brilho} scale={2.6}>
        <spriteMaterial map={textura} transparent depthWrite={false} blending={THREE.AdditiveBlending} opacity={0.25} />
      </sprite>
      <sprite ref={centro} scale={0.55}>
        <spriteMaterial map={textura} color="#fff3dc" transparent depthWrite={false} blending={THREE.AdditiveBlending} />
      </sprite>
      <group ref={grupo}>
        <points geometry={geometria} material={material} />
        <group ref={registrar(4)} rotation={[1.15, 0, 0]}>
          <Linha geometria={geo.d} cor={COR.ambar} opacidade={0.35} />
          <sprite ref={cometa} scale={0.16}>
            <spriteMaterial map={textura} transparent depthWrite={false} blending={THREE.AdditiveBlending} opacity={0} />
          </sprite>
        </group>
      </group>
      <group ref={registrar(0)}>
        <Linha geometria={geo.a} cor={COR.ambar} opacidade={0.75} traco={0.045} vao={0.03} />
      </group>
      <group ref={registrar(1)}>
        <Linha geometria={geo.b1} cor={COR.ambar} opacidade={0.6} />
        <Linha geometria={geo.b2} cor={COR.ambar} opacidade={0.6} />
        <Linha geometria={geo.b3} cor={COR.ambar} opacidade={0.6} />
      </group>
      <group ref={registrar(2)}>
        <primitive object={marcasLinha} />
      </group>
      <group ref={registrar(3)}>
        <Linha geometria={geo.e1} cor={COR.ambar} opacidade={0.25} />
        <Linha geometria={geo.e2} cor={COR.ambar} opacidade={0.25} />
      </group>
      <mesh ref={varredura}>
        <planeGeometry args={[1.7, 0.006]} />
        <meshBasicMaterial transparent opacity={0} blending={THREE.AdditiveBlending} depthWrite={false} />
      </mesh>
    </group>
  );
}

function Poeira() {
  const pontos = useRef<THREE.Points>(null);
  const geometria = useMemo(() => {
    const n = 420;
    const p = new Float32Array(n * 3);
    for (let i = 0; i < n; i++) {
      p[i * 3] = (Math.random() - 0.5) * 12;
      p[i * 3 + 1] = (Math.random() - 0.5) * 7;
      p[i * 3 + 2] = -Math.random() * 5 + 0.5;
    }
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.BufferAttribute(p, 3));
    return g;
  }, []);
  useFrame((_, delta) => {
    const pos = geometria.getAttribute("position") as THREE.BufferAttribute;
    for (let i = 0; i < pos.count; i++) {
      let y = pos.getY(i) + delta * 0.04;
      if (y > 3.5) y = -3.5;
      pos.setY(i, y);
    }
    pos.needsUpdate = true;
  });
  return (
    <points ref={pontos} geometry={geometria}>
      <pointsMaterial size={0.012} color="#8fb4cf" transparent opacity={0.35} depthWrite={false} blending={THREE.AdditiveBlending} />
    </points>
  );
}

/** Posição vertical do núcleo: 44% da altura (um pouco acima do meio). */
export const ALTURA_NUCLEO = 0.44;

export default function Nucleo() {
  // com a câmera em z=6 e fov 40, a altura visível em z=0 é ~4,37 unidades
  const deslocamento = (0.5 - ALTURA_NUCLEO) * 4.37;
  return (
    <Canvas
      className="!absolute inset-0"
      camera={{ position: [0, 0, 6], fov: 40 }}
      dpr={[1, 2]}
      gl={{ antialias: true, alpha: true, powerPreference: "high-performance" }}
      resize={{ offsetSize: true }}
      style={{ pointerEvents: "none" }}
    >
      <Poeira />
      <Sol deslocamentoY={deslocamento} />
    </Canvas>
  );
}

import { Canvas, useFrame } from "@react-three/fiber";
import { useEffect, useMemo, useRef } from "react";
import * as THREE from "three";
import { mesh } from "topojson-client";
import mundo from "world-atlas/countries-110m.json";

const RAIO = 1;

function paraVetor(lon: number, lat: number, r = RAIO): THREE.Vector3 {
  const phi = ((90 - lat) * Math.PI) / 180;
  const theta = ((lon + 180) * Math.PI) / 180;
  return new THREE.Vector3(-r * Math.sin(phi) * Math.cos(theta), r * Math.cos(phi), r * Math.sin(phi) * Math.sin(theta));
}

function geometriaFronteiras(): THREE.BufferGeometry {
  const linhas = mesh(mundo as any, (mundo as any).objects.countries) as any;
  const pontos: number[] = [];
  for (const linha of linhas.coordinates as [number, number][][]) {
    for (let i = 0; i < linha.length - 1; i++) {
      const a = paraVetor(linha[i][0], linha[i][1], RAIO * 1.001);
      const b = paraVetor(linha[i + 1][0], linha[i + 1][1], RAIO * 1.001);
      pontos.push(a.x, a.y, a.z, b.x, b.y, b.z);
    }
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.Float32BufferAttribute(pontos, 3));
  return g;
}

function geometriaGrade(): THREE.BufferGeometry {
  const pontos: number[] = [];
  const empurrar = (a: THREE.Vector3, b: THREE.Vector3) => pontos.push(a.x, a.y, a.z, b.x, b.y, b.z);
  for (let lat = -60; lat <= 60; lat += 30) {
    for (let lon = -180; lon < 180; lon += 4) empurrar(paraVetor(lon, lat), paraVetor(lon + 4, lat));
  }
  for (let lon = -180; lon < 180; lon += 30) {
    for (let lat = -88; lat < 88; lat += 4) empurrar(paraVetor(lon, lat), paraVetor(lon, lat + 4));
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.Float32BufferAttribute(pontos, 3));
  return g;
}

interface Giro {
  y: number;
  x: number;
  vy: number;
  vx: number;
  ultimoToque: number;
}

function Terra({ lat, lon, giro, cor }: { lat?: number; lon?: number; giro: React.MutableRefObject<Giro>; cor: string }) {
  const grupo = useRef<THREE.Group>(null);
  const feixe = useRef<THREE.Mesh>(null);
  const fronteiras = useMemo(geometriaFronteiras, []);
  const grade = useMemo(geometriaGrade, []);
  const posicaoCidade = useMemo(() => (lat != null && lon != null ? paraVetor(lon, lat, RAIO * 1.01) : null), [lat, lon]);
  const corThree = useMemo(() => new THREE.Color(cor), [cor]);

  useEffect(() => {
    if (lon != null) giro.current.y = -((lon + 90) * Math.PI) / 180;
    if (lat != null) giro.current.x = (lat * Math.PI) / 180 * 0.6;
  }, [lat, lon, giro]);

  useFrame((estado, delta) => {
    const g = giro.current;
    const ocioso = performance.now() - g.ultimoToque > 2500;
    g.y += g.vy * delta + (ocioso ? delta * 0.12 : 0);
    g.x = Math.max(-1.2, Math.min(1.2, g.x + g.vx * delta));
    g.vy *= Math.pow(0.08, delta);
    g.vx *= Math.pow(0.08, delta);
    if (grupo.current) {
      grupo.current.rotation.y = g.y;
      grupo.current.rotation.x = g.x;
    }
    if (feixe.current) {
      const m = feixe.current.material as THREE.MeshBasicMaterial;
      m.opacity = 0.55 + Math.sin(estado.clock.elapsedTime * 3) * 0.35;
    }
  });

  return (
    <group ref={grupo}>
      <mesh>
        <sphereGeometry args={[RAIO * 0.995, 48, 48]} />
        <meshBasicMaterial color="#06101a" transparent opacity={0.55} />
      </mesh>
      <lineSegments geometry={grade}>
        <lineBasicMaterial color="#5f7c93" transparent opacity={0.22} blending={THREE.AdditiveBlending} depthWrite={false} />
      </lineSegments>
      <lineSegments geometry={fronteiras}>
        <lineBasicMaterial color={corThree} transparent opacity={0.85} blending={THREE.AdditiveBlending} depthWrite={false} />
      </lineSegments>
      {posicaoCidade && (
        <group position={posicaoCidade} quaternion={new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0, 1, 0), posicaoCidade.clone().normalize())}>
          <mesh ref={feixe} position={[0, 0.12, 0]}>
            <cylinderGeometry args={[0.006, 0.006, 0.24, 6]} />
            <meshBasicMaterial color="#d8eeff" transparent blending={THREE.AdditiveBlending} depthWrite={false} />
          </mesh>
          <mesh rotation={[Math.PI / 2, 0, 0]}>
            <ringGeometry args={[0.025, 0.04, 32]} />
            <meshBasicMaterial color="#d8eeff" side={THREE.DoubleSide} transparent opacity={0.9} />
          </mesh>
        </group>
      )}
    </group>
  );
}

export default function Globo({ dados }: { dados: { lat?: number; lon?: number; rotulo?: string } }) {
  // começa parado mostrando a sua cidade; depois de alguns segundos gira devagar
  const giro = useRef<Giro>({ y: 0, x: 0.35, vy: 0, vx: 0, ultimoToque: performance.now() + 5000 });
  const area = useRef<HTMLDivElement>(null);
  const cor = getComputedStyle(document.documentElement).getPropertyValue("--luz").trim() || "#ffb547";

  useEffect(() => {
    const el = area.current;
    if (!el) return;
    // a mão (pinça + arrastar) manda eventos "girar" para cá
    const aoGirar = (e: Event) => {
      const { dx, dy } = (e as CustomEvent<{ dx: number; dy: number }>).detail;
      const g = giro.current;
      g.y += dx * 0.008;
      g.x += dy * 0.006;
      g.vy = dx * 0.4;
      g.vx = dy * 0.3;
      g.ultimoToque = performance.now();
    };
    el.addEventListener("girar", aoGirar);
    return () => el.removeEventListener("girar", aoGirar);
  }, []);

  const arrastando = useRef<{ x: number; y: number; t: number } | null>(null);

  return (
    <div className="w-[380px]">
      <div
        ref={area}
        data-girar
        className="h-[360px] cursor-grab active:cursor-grabbing touch-none"
        onPointerDown={(e) => {
          e.stopPropagation();
          (e.target as HTMLElement).setPointerCapture(e.pointerId);
          arrastando.current = { x: e.clientX, y: e.clientY, t: performance.now() };
        }}
        onPointerMove={(e) => {
          const a = arrastando.current;
          if (!a) return;
          const dx = e.clientX - a.x;
          const dy = e.clientY - a.y;
          const dt = Math.max(1, performance.now() - a.t) / 1000;
          const g = giro.current;
          g.y += dx * 0.008;
          g.x += dy * 0.006;
          g.vy = (dx * 0.008) / dt;
          g.vx = (dy * 0.006) / dt;
          g.ultimoToque = performance.now();
          arrastando.current = { x: e.clientX, y: e.clientY, t: performance.now() };
        }}
        onPointerUp={() => (arrastando.current = null)}
      >
        <Canvas camera={{ position: [0, 0, 3.1], fov: 40 }} dpr={[1, 2]} gl={{ alpha: true, antialias: true }} resize={{ offsetSize: true }}>
          <Terra lat={dados?.lat} lon={dados?.lon} giro={giro} cor={cor} />
        </Canvas>
      </div>
      <p className="text-xs text-aco text-center">
        {dados?.rotulo ? `Você está em ${dados.rotulo}. ` : ""}Arraste ou faça uma pinça para girar.
      </p>
    </div>
  );
}

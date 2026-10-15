// Baixa o modelo (com o token, como as outras chamadas à API) e transforma em peças (geometrias só com posição).
import * as THREE from "three";
import { comToken, token } from "../../lib/api";
import { mergeGeometries } from "three/examples/jsm/utils/BufferGeometryUtils.js";
import { MAX_PECAS, separarPecas } from "./pecas";
import type { Formato } from "./tipos";

export interface ModeloCarregado {
  pecas: THREE.BufferGeometry[];
  triangulos: number;
}

async function baixar(url: string, sinal: AbortSignal): Promise<ArrayBuffer> {
  const cabecalhos = new Headers();
  const t = token();
  if (t) cabecalhos.set("Authorization", `Bearer ${t}`);
  const resposta = await fetch(url, { headers: cabecalhos, signal: sinal });
  if (!resposta.ok) {
    let mensagem = `Erro ${resposta.status} ao baixar o modelo`;
    try {
      const dados = await resposta.json();
      mensagem = dados.erro ?? dados.detail ?? mensagem;
    } catch {
      /* sem JSON */
    }
    throw new Error(mensagem);
  }
  return resposta.arrayBuffer();
}

/** Gerente de carga: buffers e texturas de .gltf vêm da mesma rota, com o token na URL. */
function gerenteComToken(): THREE.LoadingManager {
  const gerente = new THREE.LoadingManager();
  gerente.setURLModifier((url) => (url.startsWith("/api/oficina/") ? comToken(url) : url));
  return gerente;
}

async function cena(formato: Formato, dados: ArrayBuffer, url: string): Promise<THREE.Object3D | THREE.BufferGeometry> {
  const base = `${url}/`;
  switch (formato) {
    case "stl": {
      const { STLLoader } = await import("three/examples/jsm/loaders/STLLoader.js");
      return new STLLoader().parse(dados);
    }
    case "obj": {
      const { OBJLoader } = await import("three/examples/jsm/loaders/OBJLoader.js");
      return new OBJLoader().parse(new TextDecoder().decode(dados));
    }
    case "glb":
    case "gltf": {
      const { GLTFLoader } = await import("three/examples/jsm/loaders/GLTFLoader.js");
      const gltf = await new GLTFLoader(gerenteComToken()).parseAsync(dados, base);
      return gltf.scene;
    }
    case "fbx": {
      const { FBXLoader } = await import("three/examples/jsm/loaders/FBXLoader.js");
      return new FBXLoader(gerenteComToken()).parse(dados, base);
    }
    case "3mf": {
      const { ThreeMFLoader } = await import("three/examples/jsm/loaders/3MFLoader.js");
      return new ThreeMFLoader().parse(dados);
    }
  }
  throw new Error(`Formato ${formato} não suportado`);
}

/** Só posições (o material holográfico calcula o resto), sem índice, já na posição do mundo. */
function soPosicoes(geometria: THREE.BufferGeometry, matriz?: THREE.Matrix4): THREE.BufferGeometry | null {
  const posicao = geometria.getAttribute("position");
  if (!posicao || posicao.count < 3) return null;
  // copia vértice a vértice: funciona com índice, atributos intercalados (glTF) e quantizados
  const indice = geometria.index;
  const n = indice ? indice.count : posicao.count;
  const v = new THREE.Vector3();
  const total = n - (n % 3);
  const arr = new Float32Array(total * 3);
  for (let i = 0; i < total; i++) {
    v.fromBufferAttribute(posicao, indice ? indice.getX(i) : i);
    if (matriz) v.applyMatrix4(matriz);
    arr[i * 3] = v.x;
    arr[i * 3 + 1] = v.y;
    arr[i * 3 + 2] = v.z;
  }
  const plana = new THREE.BufferGeometry();
  plana.setAttribute("position", new THREE.BufferAttribute(arr, 3));
  return plana;
}

function liberarCena(objeto: THREE.Object3D) {
  objeto.traverse((o) => {
    const malha = o as THREE.Mesh;
    malha.geometry?.dispose?.();
    const materiais = Array.isArray(malha.material) ? malha.material : malha.material ? [malha.material] : [];
    for (const m of materiais) {
      for (const valor of Object.values(m)) if (valor instanceof THREE.Texture) valor.dispose();
      m.dispose();
    }
  });
}

export async function carregarModelo(url: string, formato: Formato, sinal: AbortSignal): Promise<ModeloCarregado> {
  const dados = await baixar(url, sinal);
  const resultado = await cena(formato, dados, url);
  let pecas: THREE.BufferGeometry[] = [];
  if (resultado instanceof THREE.BufferGeometry) {
    const g = soPosicoes(resultado);
    resultado.dispose();
    if (g) pecas.push(g);
  } else {
    resultado.updateMatrixWorld(true);
    resultado.traverse((o) => {
      const malha = o as THREE.Mesh;
      if (!malha.isMesh || !malha.geometry) return;
      const g = soPosicoes(malha.geometry, malha.matrixWorld);
      if (g) pecas.push(g);
    });
    liberarCena(resultado);
  }
  if (!pecas.length) throw new Error("O arquivo não tem nenhuma malha para mostrar.");

  // uma malha só (STL, OBJ de um objeto): tenta separar em peças soltas
  if (pecas.length === 1) {
    const separadas = await separarPecas(pecas[0].getAttribute("position").array as Float32Array, { sinal });
    if (sinal.aborted) throw new DOMException("cancelado", "AbortError");
    if (separadas && separadas.length > 1) {
      pecas[0].dispose();
      pecas = separadas.map((p) => {
        const g = new THREE.BufferGeometry();
        g.setAttribute("position", new THREE.BufferAttribute(p, 3));
        return g;
      });
    }
  }

  // malhas demais: as maiores ficam soltas, o resto vira uma peça só
  if (pecas.length > MAX_PECAS) {
    pecas.sort((a, b) => b.getAttribute("position").count - a.getAttribute("position").count);
    const resto = pecas.splice(MAX_PECAS - 1);
    const junto = mergeGeometries(resto, false);
    resto.forEach((g) => g.dispose());
    if (junto) pecas.push(junto);
  }
  for (const g of pecas) g.computeVertexNormals();
  const triangulos = pecas.reduce((n, g) => n + g.getAttribute("position").count / 3, 0);
  return { pecas, triangulos };
}

import { Canvas, useFrame, type ThreeEvent } from "@react-three/fiber";
import { OrbitControls, Environment, Lightformer, ContactShadows, Text } from "@react-three/drei";
import { useMemo, useRef, forwardRef, useImperativeHandle } from "react";
import * as THREE from "three";
import type { OrbitControls as OrbitImpl } from "three-stdlib";

const C = {
  blue: "#2f56e0", blueDark: "#2342b8", roof: "#3a63ea", floor: "#e9ecf2", road: "#cfd5df",
  yellow: "#f4c21b", box: "#d9a86a", boxDark: "#b98a50", wood: "#a8794a", tree: "#6fb98a", trunk: "#8b6a4a",
  white: "#f7f8fb", teal: "#2e9d9a", black: "#2a2d36", pin: "#2f6bf2",
};

export type Pick = { type: "truck" | "forklift"; id: string } | null;
export interface SceneHandle { zoom: (f: number) => void; rotate: (a: number) => void; reset: () => void }

function Box({ p, s = [0.5, 0.4, 0.5] }: { p: [number, number, number]; s?: [number, number, number] }) {
  return (
    <mesh position={p} castShadow>
      <boxGeometry args={s} />
      <meshStandardMaterial color={C.box} roughness={0.8} />
    </mesh>
  );
}

function Pallet({ p, stack = 2 }: { p: [number, number, number]; stack?: number }) {
  const boxes = [];
  for (let y = 0; y < stack; y++)
    for (let x = 0; x < 2; x++) for (let z = 0; z < 2; z++)
      boxes.push(<Box key={`${x}${y}${z}`} p={[x * 0.52 - 0.26, 0.28 + y * 0.42, z * 0.52 - 0.26]} />);
  return (
    <group position={p}>
      <mesh position={[0, 0.05, 0]} castShadow><boxGeometry args={[1.1, 0.1, 1.1]} /><meshStandardMaterial color={C.wood} /></mesh>
      {boxes}
    </group>
  );
}

function Pin({ p }: { p: [number, number, number] }) {
  const ref = useRef<THREE.Group>(null);
  useFrame(({ clock }) => { if (ref.current) ref.current.position.y = p[1] + Math.sin(clock.elapsedTime * 2 + p[0]) * 0.15; });
  return (
    <group ref={ref} position={p}>
      <mesh><sphereGeometry args={[0.35, 24, 24]} /><meshStandardMaterial color={C.pin} /></mesh>
      <mesh position={[0, -0.45, 0]} rotation={[Math.PI, 0, 0]}><coneGeometry args={[0.3, 0.6, 24]} /><meshStandardMaterial color={C.pin} /></mesh>
      <mesh position={[0, 0, 0.3]}><sphereGeometry args={[0.13, 16, 16]} /><meshStandardMaterial color={C.white} /></mesh>
    </group>
  );
}

function Tree({ p }: { p: [number, number, number] }) {
  return (
    <group position={p}>
      <mesh position={[0, 0.5, 0]} castShadow><cylinderGeometry args={[0.08, 0.1, 1]} /><meshStandardMaterial color={C.trunk} /></mesh>
      <mesh position={[0, 1.35, 0]} castShadow><sphereGeometry args={[0.55, 20, 20]} /><meshStandardMaterial color={C.tree} roughness={0.9} /></mesh>
    </group>
  );
}

function Building({ p, w, d, h, label }: { p: [number, number, number]; w: number; d: number; h: number; label?: string }) {
  const doors = Math.max(1, Math.floor(w / 2.2));
  return (
    <group position={p}>
      <mesh position={[0, h / 2, 0]} castShadow receiveShadow><boxGeometry args={[w, h, d]} /><meshStandardMaterial color={C.blue} roughness={0.5} /></mesh>
      {/* roof ridge */}
      <mesh position={[0, h + 0.35, 0]} rotation={[0, 0, Math.PI / 4]} castShadow>
        <boxGeometry args={[0.5 * Math.SQRT2 * 1.4, 0.5 * Math.SQRT2 * 1.4, d + 0.1]} />
        <meshStandardMaterial color={C.roof} />
      </mesh>
      <mesh position={[0, h + 0.02, 0]}><boxGeometry args={[w + 0.15, 0.06, d + 0.15]} /><meshStandardMaterial color={C.blueDark} /></mesh>
      {/* corrugation */}
      {Array.from({ length: Math.floor(w * 3) }).map((_, i) => (
        <mesh key={i} position={[-w / 2 + (i + 0.5) / 3, h / 2, d / 2 + 0.01]}><boxGeometry args={[0.04, h, 0.02]} /><meshStandardMaterial color={C.blueDark} /></mesh>
      ))}
      {Array.from({ length: doors }).map((_, i) => {
        const x = -w / 2 + (w / doors) * (i + 0.5);
        return (
          <group key={i} position={[x, 0, d / 2 + 0.03]}>
            <mesh position={[0, 0.9, 0]}><boxGeometry args={[1.4, 1.8, 0.05]} /><meshStandardMaterial color={C.white} /></mesh>
            <mesh position={[0, 0.85, 0.03]}><boxGeometry args={[1.2, 1.6, 0.04]} /><meshStandardMaterial color="#c9a273" /></mesh>
            <Box p={[-0.25, 0.25, 0.3]} /><Box p={[0.3, 0.25, 0.3]} /><Box p={[0, 0.65, 0.3]} />
          </group>
        );
      })}
      {label && (
        <Text position={[0, h * 0.75, d / 2 + 0.05]} fontSize={0.35} color={C.white} anchorX="center">{label}</Text>
      )}
    </group>
  );
}

const Wheel = ({ p }: { p: [number, number, number] }) => (
  <mesh position={p} rotation={[0, 0, Math.PI / 2]}><cylinderGeometry args={[0.28, 0.28, 0.2, 20]} /><meshStandardMaterial color={C.black} /></mesh>
);

function TruckModel({ color, label, selected }: { color: string; label: string; selected: boolean }) {
  return (
    <group>
      <mesh position={[0, 1.15, -0.8]} castShadow><boxGeometry args={[1.6, 1.7, 3.6]} /><meshStandardMaterial color={C.white} emissive={selected ? "#3a6cff" : "#000"} emissiveIntensity={selected ? 0.25 : 0} /></mesh>
      <mesh position={[0.81, 1.2, -0.8]}><boxGeometry args={[0.02, 0.5, 2.4]} /><meshStandardMaterial color={color} /></mesh>
      <Text position={[0.83, 1.2, -0.8]} rotation={[0, Math.PI / 2, 0]} fontSize={0.22} color={C.white}>{label}</Text>
      <mesh position={[0, 0.85, 1.55]} castShadow><boxGeometry args={[1.6, 1.1, 1.1]} /><meshStandardMaterial color={color} /></mesh>
      <mesh position={[0, 1.05, 2.11]}><boxGeometry args={[1.3, 0.45, 0.02]} /><meshStandardMaterial color="#9fc2ff" metalness={0.4} roughness={0.1} /></mesh>
      {[[-0.75, 0.28, 1.5], [0.75, 0.28, 1.5], [-0.75, 0.28, -1.6], [0.75, 0.28, -1.6], [-0.75, 0.28, -0.9], [0.75, 0.28, -0.9]].map((w, i) => <Wheel key={i} p={w as [number, number, number]} />)}
    </group>
  );
}

function Truck({ id, color, label, path, onPick, selected }: { id: string; color: string; label: string; path: "dock" | "road"; onPick: (p: Pick) => void; selected: boolean }) {
  const ref = useRef<THREE.Group>(null);
  useFrame(({ clock }) => {
    const g = ref.current; if (!g) return;
    const t = clock.elapsedTime;
    if (path === "road") {
      const z = ((t * 1.6) % 30) - 15;
      g.position.set(9.5, 0, -z); g.rotation.y = Math.PI;
    } else {
      const k = (Math.sin(t * 0.25) + 1) / 2; // backs into dock and pulls out
      g.position.set(-3.2, 0, 6 + k * 2); g.rotation.y = Math.PI;
    }
  });
  return (
    <group ref={ref} onClick={(e: ThreeEvent<MouseEvent>) => { e.stopPropagation(); onPick({ type: "truck", id }); }}
      onPointerOver={() => (document.body.style.cursor = "pointer")} onPointerOut={() => (document.body.style.cursor = "")}>
      <TruckModel color={color} label={label} selected={selected} />
    </group>
  );
}

function Forklift({ id, center, radius, speed, onPick, selected }: { id: string; center: [number, number]; radius: number; speed: number; onPick: (p: Pick) => void; selected: boolean }) {
  const ref = useRef<THREE.Group>(null);
  const forks = useRef<THREE.Group>(null);
  useFrame(({ clock }) => {
    const t = clock.elapsedTime * speed;
    if (ref.current) {
      ref.current.position.set(center[0] + Math.cos(t) * radius, 0, center[1] + Math.sin(t) * radius * 0.6);
      ref.current.rotation.y = -t;
    }
    if (forks.current) forks.current.position.y = 0.2 + (Math.sin(clock.elapsedTime * 1.5) + 1) * 0.3;
  });
  return (
    <group ref={ref} onClick={(e: ThreeEvent<MouseEvent>) => { e.stopPropagation(); onPick({ type: "forklift", id }); }}
      onPointerOver={() => (document.body.style.cursor = "pointer")} onPointerOut={() => (document.body.style.cursor = "")}>
      <mesh position={[0, 0.45, 0]} castShadow><boxGeometry args={[0.8, 0.6, 1.1]} /><meshStandardMaterial color={C.yellow} emissive={selected ? "#ffb000" : "#000"} emissiveIntensity={selected ? 0.4 : 0} /></mesh>
      <mesh position={[0, 0.85, -0.35]} castShadow><boxGeometry args={[0.75, 0.4, 0.4]} /><meshStandardMaterial color={C.black} /></mesh>
      {[[-0.35, 1.2, 0.3], [0.35, 1.2, 0.3], [-0.35, 1.2, -0.25], [0.35, 1.2, -0.25]].map((p, i) => (
        <mesh key={i} position={p as [number, number, number]}><boxGeometry args={[0.05, 0.9, 0.05]} /><meshStandardMaterial color={C.black} /></mesh>
      ))}
      <mesh position={[0, 1.66, 0.02]}><boxGeometry args={[0.8, 0.05, 0.65]} /><meshStandardMaterial color={C.yellow} /></mesh>
      <mesh position={[0, 1.0, 0.6]}><boxGeometry args={[0.6, 1.6, 0.06]} /><meshStandardMaterial color={C.black} /></mesh>
      <group ref={forks} position={[0, 0.2, 0.9]}>
        <mesh position={[-0.18, 0, 0]}><boxGeometry args={[0.08, 0.04, 0.6]} /><meshStandardMaterial color={C.black} /></mesh>
        <mesh position={[0.18, 0, 0]}><boxGeometry args={[0.08, 0.04, 0.6]} /><meshStandardMaterial color={C.black} /></mesh>
        <Box p={[0, 0.22, 0]} s={[0.5, 0.4, 0.5]} />
      </group>
      {[[-0.42, 0.18, 0.35], [0.42, 0.18, 0.35], [-0.42, 0.18, -0.35], [0.42, 0.18, -0.35]].map((p, i) => (
        <mesh key={i} position={p as [number, number, number]} rotation={[0, 0, Math.PI / 2]}><cylinderGeometry args={[0.18, 0.18, 0.12, 16]} /><meshStandardMaterial color={C.black} /></mesh>
      ))}
    </group>
  );
}

function Container({ p }: { p: [number, number, number] }) {
  return (
    <group position={p} rotation={[0, 0.3, 0]}>
      <mesh position={[0, 0.9, 0]} castShadow><boxGeometry args={[2, 1.8, 4]} /><meshStandardMaterial color={C.teal} /></mesh>
      {Array.from({ length: 10 }).map((_, i) => (
        <mesh key={i} position={[1.01, 0.9, -1.8 + i * 0.4]}><boxGeometry args={[0.02, 1.7, 0.08]} /><meshStandardMaterial color="#247d7b" /></mesh>
      ))}
      <Text position={[1.03, 1, 0]} rotation={[0, Math.PI / 2, 0]} fontSize={0.35} color={C.white}>MAERA LINE</Text>
    </group>
  );
}

function Ground() {
  const tex = useMemo(() => {
    const c = document.createElement("canvas"); c.width = c.height = 512;
    const g = c.getContext("2d")!;
    g.fillStyle = C.floor; g.fillRect(0, 0, 512, 512);
    for (let i = 0; i < 2500; i++) { g.fillStyle = `rgba(120,130,150,${Math.random() * 0.05})`; g.fillRect(Math.random() * 512, Math.random() * 512, 3, 3); }
    g.strokeStyle = "rgba(150,160,180,0.35)"; g.lineWidth = 2;
    for (let i = 0; i <= 512; i += 128) { g.beginPath(); g.moveTo(i, 0); g.lineTo(i, 512); g.stroke(); g.beginPath(); g.moveTo(0, i); g.lineTo(512, i); g.stroke(); }
    const t = new THREE.CanvasTexture(c); t.wrapS = t.wrapT = THREE.RepeatWrapping; t.repeat.set(10, 10); t.colorSpace = THREE.SRGBColorSpace;
    return t;
  }, []);
  return (
    <>
      <mesh rotation={[-Math.PI / 2, 0, 0]} receiveShadow><planeGeometry args={[60, 60]} /><meshStandardMaterial map={tex} /></mesh>
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[9.5, 0.01, 0]} receiveShadow><planeGeometry args={[4, 60]} /><meshStandardMaterial color={C.road} /></mesh>
      {Array.from({ length: 15 }).map((_, i) => (
        <mesh key={i} rotation={[-Math.PI / 2, 0, 0]} position={[9.5, 0.02, -28 + i * 4]}><planeGeometry args={[0.15, 1.6]} /><meshStandardMaterial color={C.white} /></mesh>
      ))}
      {/* yellow dock lines */}
      {[-5.6, -3.2, -0.8].map((x, i) => (
        <mesh key={i} rotation={[-Math.PI / 2, 0, 0]} position={[x, 0.02, 5.5]}><planeGeometry args={[0.08, 4]} /><meshStandardMaterial color={C.yellow} /></mesh>
      ))}
    </>
  );
}

const SceneContent = forwardRef<SceneHandle, { night: boolean; onPick: (p: Pick) => void; selected: Pick; onReady: () => void }>(
  function SceneContent({ night, onPick, selected, onReady }, ref) {
    const controls = useRef<OrbitImpl>(null);
    const ready = useRef(false);
    useFrame(() => { if (!ready.current) { ready.current = true; onReady(); } });
    useImperativeHandle(ref, () => ({
      zoom: (f) => { const c = controls.current; if (!c) return; const o = c.object; o.position.sub(c.target).multiplyScalar(f).add(c.target); c.update(); },
      rotate: (a) => { const c = controls.current; if (!c) return; const o = c.object; const v = o.position.clone().sub(c.target); v.applyAxisAngle(new THREE.Vector3(0, 1, 0), a); o.position.copy(c.target).add(v); c.update(); },
      reset: () => { const c = controls.current; if (!c) return; c.object.position.set(16, 16, 18); c.target.set(0, 0, 0); c.update(); },
    }));
    const isSel = (t: string, id: string) => selected?.type === t && selected.id === id;
    return (
      <>
        <color attach="background" args={[night ? "#141a2e" : "#eef1f6"]} />
        <ambientLight intensity={night ? 0.25 : 0.6} />
        <directionalLight position={[10, 18, 8]} intensity={night ? 0.4 : 1.6} castShadow shadow-mapSize={[2048, 2048]}
          shadow-camera-left={-20} shadow-camera-right={20} shadow-camera-top={20} shadow-camera-bottom={-20} color={night ? "#9fb4ff" : "#fff"} />
        {night && [[-3, 3, 4], [1, 3, 4], [6, 3, 0]].map((p, i) => <pointLight key={i} position={p as [number, number, number]} intensity={12} distance={9} color="#ffd38a" />)}
        <Environment resolution={64}>
          <Lightformer intensity={night ? 0.4 : 1.6} position={[0, 6, 0]} rotation-x={Math.PI / 2} scale={[12, 12, 1]} />
          <Lightformer intensity={0.8} color="#bcd0ff" position={[-6, 2, 0]} rotation-y={Math.PI / 2} scale={[20, 2, 1]} />
        </Environment>
        <Ground />
        <Building p={[-3, 0, 0]} w={6} d={5} h={2.8} />
        <Building p={[2.6, 0, 1]} w={5} d={4.5} h={2.4} label="WH-01" />
        <Container p={[-10, 0, 3]} />
        <Pallet p={[-7.5, 0, 6]} /><Pallet p={[-6.2, 0, 7.5]} /><Pallet p={[-8.6, 0, 8]} stack={1} />
        <Pallet p={[5.5, 0, 5.5]} stack={3} /><Pallet p={[0.8, 0, 6.5]} /><Pallet p={[6.8, 0, -4]} />
        {/* racking */}
        <group position={[4, 0, -4.5]}>
          {[0, 1, 2].map((y) => (
            <group key={y}>
              <mesh position={[0, 0.9 + y * 0.9, 0]}><boxGeometry args={[2.4, 0.06, 0.9]} /><meshStandardMaterial color="#8a93a6" /></mesh>
              <Box p={[-0.6, 1.15 + y * 0.9, 0]} /><Box p={[0.1, 1.15 + y * 0.9, 0]} /><Box p={[0.7, 1.15 + y * 0.9, 0]} />
            </group>
          ))}
          {[[-1.2, 0.45], [1.2, 0.45], [-1.2, -0.45], [1.2, -0.45]].map(([x, z], i) => (
            <mesh key={i} position={[x!, 1.6, z!]}><boxGeometry args={[0.08, 3.2, 0.08]} /><meshStandardMaterial color="#5c6576" /></mesh>
          ))}
        </group>
        {[[-6, -6], [-2, -7.5], [1.5, -8], [7.5, -8], [12.5, -4], [12.5, 4], [-12, -3], [12.5, 10]].map(([x, z], i) => <Tree key={i} p={[x!, 0, z!]} />)}
        <Pin p={[0.8, 3.2, 6.5]} /><Pin p={[5.5, 3.6, 5.5]} /><Pin p={[6.8, 2.6, -4]} />
        <Truck id="TRK-2051" color={C.blue} label="LastMileDelivery" path="dock" onPick={onPick} selected={isSel("truck", "TRK-2051")} />
        <Truck id="TRK-2287" color="#1e2f6b" label="Bluepeak" path="road" onPick={onPick} selected={isSel("truck", "TRK-2287")} />
        <Forklift id="FL-01" center={[-1, 6]} radius={2} speed={0.4} onPick={onPick} selected={isSel("forklift", "FL-01")} />
        <Forklift id="FL-02" center={[-7.5, 0]} radius={1} speed={0.25} onPick={onPick} selected={isSel("forklift", "FL-02")} />
        <ContactShadows position={[0, 0.03, 0]} opacity={0.35} scale={40} blur={2.5} far={6} />
        <OrbitControls ref={controls} makeDefault enableDamping maxPolarAngle={Math.PI / 2.3} minDistance={8} maxDistance={45} />
      </>
    );
  },
);

export const WarehouseScene = forwardRef<SceneHandle, { night: boolean; onPick: (p: Pick) => void; selected: Pick; onReady: () => void }>(
  function WarehouseScene(props, ref) {
    return (
      <Canvas shadows dpr={[1, 2]} camera={{ position: [16, 16, 18], fov: 35 }} onPointerMissed={() => props.onPick(null)}>
        <SceneContent ref={ref} {...props} />
      </Canvas>
    );
  },
);

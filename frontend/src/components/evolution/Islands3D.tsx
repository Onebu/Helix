import { useRef, useState, useEffect, useMemo, useCallback, Component } from 'react'
import type { ReactNode, ErrorInfo } from 'react'
import { useTranslation } from 'react-i18next'
import { Canvas, useFrame } from '@react-three/fiber'
import { OrbitControls, Html } from '@react-three/drei'
import * as THREE from 'three'
import type { CandidateData, MigrationData, LineageNode } from '../../types/evolution'
import { fitnessColor, ISLAND_COLORS, REJECTED_OPACITY, ACTIVE_OPACITY, FITNESS_DOMAIN_MIN, FITNESS_DOMAIN_MAX } from '../../lib/scoring'
import { DiffPopover } from './DiffPopover'

// ---------------------------------------------------------------------------
// WebGL availability check
// ---------------------------------------------------------------------------
function isWebGLAvailable(): boolean {
  try {
    const canvas = document.createElement('canvas')
    return !!(canvas.getContext('webgl2') || canvas.getContext('webgl'))
  } catch {
    return false
  }
}

// ---------------------------------------------------------------------------
// Error boundary for 3D render failures
// ---------------------------------------------------------------------------
interface CanvasErrorBoundaryState { hasError: boolean }

function CanvasRenderErrorFallback() {
  const { t } = useTranslation()
  return (
    <div className="flex items-center justify-center h-[500px] bg-slate-800 border border-slate-700 rounded-lg">
      <p className="text-slate-400">{t('evolution.webglRequired')}</p>
    </div>
  )
}

class CanvasErrorBoundary extends Component<{ children: ReactNode }, CanvasErrorBoundaryState> {
  constructor(props: { children: ReactNode }) {
    super(props)
    this.state = { hasError: false }
  }

  static getDerivedStateFromError(_: Error): CanvasErrorBoundaryState {
    return { hasError: true }
  }

  componentDidCatch(_error: Error, _info: ErrorInfo) {
    // Render failure is surfaced via the fallback UI
  }

  render() {
    if (this.state.hasError) {
      return <CanvasRenderErrorFallback />
    }
    return this.props.children
  }
}

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------
interface Islands3DProps {
  candidates: CandidateData[]
  migrations: MigrationData[]
  islandCount: number
  seedFitness?: number | null
  lineageEvents?: LineageNode[]
}

interface IslandLayout {
  position: [number, number, number]
  color: string
  index: number
}

// ---------------------------------------------------------------------------
// Island layout computation
// ---------------------------------------------------------------------------
function computeIslandLayout(islandCount: number): IslandLayout[] {
  if (islandCount <= 0) return []
  const SPACING = 4
  const layouts: IslandLayout[] = []

  if (islandCount <= 6) {
    // Circular arrangement
    const radius = islandCount === 1 ? 0 : SPACING
    for (let i = 0; i < islandCount; i++) {
      const angle = (2 * Math.PI * i) / islandCount - Math.PI / 2
      const x = islandCount === 1 ? 0 : radius * Math.cos(angle)
      const y = islandCount === 1 ? 0 : radius * Math.sin(angle)
      layouts.push({
        position: [x, y, 0],
        color: ISLAND_COLORS[i % ISLAND_COLORS.length],
        index: i,
      })
    }
  } else {
    // Grid arrangement
    const cols = Math.ceil(Math.sqrt(islandCount))
    const rows = Math.ceil(islandCount / cols)
    const offsetX = ((cols - 1) * SPACING) / 2
    const offsetY = ((rows - 1) * SPACING) / 2
    for (let i = 0; i < islandCount; i++) {
      const col = i % cols
      const row = Math.floor(i / cols)
      layouts.push({
        position: [col * SPACING - offsetX, row * SPACING - offsetY, 0],
        color: ISLAND_COLORS[i % ISLAND_COLORS.length],
        index: i,
      })
    }
  }

  return layouts
}

// ---------------------------------------------------------------------------
// Random point inside unit sphere (cube rejection sampling)
// ---------------------------------------------------------------------------
function randomPointInSphere(radius: number): [number, number, number] {
  let x: number, y: number, z: number
  do {
    x = (Math.random() - 0.5) * 2
    y = (Math.random() - 0.5) * 2
    z = (Math.random() - 0.5) * 2
  } while (x * x + y * y + z * z > 1)
  return [x * radius, y * radius, z * radius]
}

// ---------------------------------------------------------------------------
// Island Sphere sub-component (renders inside Canvas)
// ---------------------------------------------------------------------------
const ISLAND_RADIUS = 1.5

function IslandSphere({ layout }: { layout: IslandLayout }) {
  return (
    <group position={layout.position}>
      <mesh>
        <sphereGeometry args={[ISLAND_RADIUS, 32, 32]} />
        <meshPhysicalMaterial
          color={layout.color}
          transparent
          opacity={0.15}
          roughness={0.35}
          metalness={0.15}
          clearcoat={0.3}
          clearcoatRoughness={0.4}
          side={THREE.DoubleSide}
        />
      </mesh>
      <Html position={[0, ISLAND_RADIUS + 0.3, 0]} center>
        <div className="text-xs text-slate-400 whitespace-nowrap select-none pointer-events-none">
          Island {layout.index}
        </div>
      </Html>
    </group>
  )
}

// ---------------------------------------------------------------------------
// Island Particle Field sub-component (fitness-reactive orbiting particles)
// ---------------------------------------------------------------------------
const MAX_FIELD_PARTICLES = 40

interface ParticleOrbitalParams {
  radius: number
  speed: number
  phase: number
  axisTheta: number // tilt angle for orbit plane
  axisPhi: number   // rotation of orbit plane
}

function IslandParticleField({
  layout,
  bestFitness,
}: {
  layout: IslandLayout
  bestFitness: number
}) {
  const meshRef = useRef<THREE.InstancedMesh>(null!)
  const tempObj = useMemo(() => new THREE.Object3D(), [])

  // Normalize fitness to 0-1 range
  const normalizedFitness = useMemo(() => {
    const raw = (bestFitness - FITNESS_DOMAIN_MIN) / (FITNESS_DOMAIN_MAX - FITNESS_DOMAIN_MIN)
    return Math.max(0, Math.min(1, raw))
  }, [bestFitness])

  // Visible particle count scales with fitness
  const visibleCount = useMemo(
    () => Math.floor(20 + 20 * normalizedFitness),
    [normalizedFitness],
  )

  // Pre-compute orbital parameters (deterministic, seeded by particle index)
  const orbitalParams = useMemo(() => {
    const params: ParticleOrbitalParams[] = []
    for (let i = 0; i < MAX_FIELD_PARTICLES; i++) {
      // Deterministic pseudo-random using golden ratio offsets
      const golden = 1.618033988749895
      const r = ISLAND_RADIUS * (1.0 + 0.8 * ((i * golden) % 1))
      const speed = 0.3 + 0.4 * (((i * 7 + 3) * golden) % 1)
      const phase = (i * golden * 2 * Math.PI) % (2 * Math.PI)
      const axisTheta = Math.acos(1 - 2 * (((i * 13 + 5) * golden) % 1)) // uniform on sphere
      const axisPhi = ((i * 17 + 11) * golden * 2 * Math.PI) % (2 * Math.PI)
      params.push({ radius: r, speed, phase, axisTheta, axisPhi })
    }
    return params
  }, [])

  const islandColor = useMemo(() => new THREE.Color(layout.color), [layout.color])

  useFrame(({ clock }) => {
    if (!meshRef.current || typeof meshRef.current.setMatrixAt !== 'function') return
    const t = clock.elapsedTime
    const speedMultiplier = 1 + normalizedFitness

    for (let i = 0; i < visibleCount; i++) {
      const p = orbitalParams[i]
      const angle = t * p.speed * speedMultiplier + p.phase

      // Orbit in a tilted plane around the island center
      const cosA = Math.cos(angle) * p.radius
      const sinA = Math.sin(angle) * p.radius

      // Apply tilt via spherical axis
      const st = Math.sin(p.axisTheta)
      const ct = Math.cos(p.axisTheta)
      const sp = Math.sin(p.axisPhi)
      const cp = Math.cos(p.axisPhi)

      // Simple tilted circular orbit
      const lx = cosA
      const ly = sinA * ct
      const lz = sinA * st

      // Rotate by axisPhi around Y
      const rx = lx * cp - lz * sp
      const rz = lx * sp + lz * cp

      tempObj.position.set(
        layout.position[0] + rx,
        layout.position[1] + ly,
        layout.position[2] + rz,
      )
      tempObj.scale.setScalar(1)
      tempObj.updateMatrix()
      meshRef.current.setMatrixAt(i, tempObj.matrix)
    }

    meshRef.current.count = visibleCount
    meshRef.current.instanceMatrix.needsUpdate = true
  })

  return (
    <instancedMesh
      ref={meshRef}
      args={[undefined, undefined, MAX_FIELD_PARTICLES]}
    >
      <sphereGeometry args={[0.02, 6, 6]} />
      <meshStandardMaterial
        color={islandColor}
        transparent
        opacity={0.6}
        emissive={islandColor}
        emissiveIntensity={0.3}
      />
    </instancedMesh>
  )
}

// ---------------------------------------------------------------------------
// Ripple Effect sub-component (pulse ring on new candidate arrival)
// ---------------------------------------------------------------------------
function RippleEffect({
  position,
  color,
  trigger,
}: {
  position: [number, number, number]
  color: string
  trigger: number
}) {
  const ringRef = useRef<THREE.Mesh>(null!)
  const matRef = useRef<THREE.MeshBasicMaterial>(null!)
  const progressRef = useRef(1) // 1 = animation complete (invisible)
  const prevTriggerRef = useRef(trigger)

  // Detect trigger changes to start animation
  useEffect(() => {
    if (trigger > prevTriggerRef.current) {
      progressRef.current = 0 // restart animation
    }
    prevTriggerRef.current = trigger
  }, [trigger])

  useFrame((_, delta) => {
    if (progressRef.current >= 1) {
      // Animation complete -- hide
      if (ringRef.current) ringRef.current.visible = false
      return
    }

    // Advance progress (1.5 second animation)
    progressRef.current = Math.min(1, progressRef.current + delta / 1.5)
    const p = progressRef.current

    if (ringRef.current && matRef.current) {
      ringRef.current.visible = true

      // Expand ring outward
      const outerRadius = ISLAND_RADIUS + (ISLAND_RADIUS * 1.5) * p
      const innerRadius = ISLAND_RADIUS + (ISLAND_RADIUS * 1.3) * p
      ringRef.current.geometry.dispose()
      ringRef.current.geometry = new THREE.RingGeometry(innerRadius, outerRadius, 32)

      // Fade opacity
      matRef.current.opacity = 0.7 * (1 - p)
    }
  })

  return (
    <mesh ref={ringRef} position={position} rotation={[Math.PI / 2, 0, 0]} visible={false}>
      <ringGeometry args={[ISLAND_RADIUS, ISLAND_RADIUS + 0.05, 32]} />
      <meshBasicMaterial
        ref={matRef}
        color={color}
        transparent
        opacity={0}
        side={THREE.DoubleSide}
      />
    </mesh>
  )
}

// ---------------------------------------------------------------------------
// Candidate Particles sub-component (InstancedMesh inside Canvas)
// ---------------------------------------------------------------------------
const MAX_PARTICLES = 500

function CandidateParticles({
  candidates,
  islandLayouts,
  offsets,
}: {
  candidates: CandidateData[]
  islandLayouts: IslandLayout[]
  offsets: [number, number, number][]
}) {
  const meshRef = useRef<THREE.InstancedMesh>(null!)
  const tempObj = useMemo(() => new THREE.Object3D(), [])
  const tempColor = useMemo(() => new THREE.Color(), [])

  useEffect(() => {
    if (!meshRef.current || typeof meshRef.current.setMatrixAt !== 'function') return
    const count = Math.min(candidates.length, MAX_PARTICLES)

    for (let i = 0; i < count; i++) {
      const c = candidates[i]
      const layout = islandLayouts[c.island] ?? islandLayouts[0]
      if (!layout) continue

      const [ox, oy, oz] = offsets[i]
      tempObj.position.set(
        layout.position[0] + ox,
        layout.position[1] + oy,
        layout.position[2] + oz,
      )
      tempObj.scale.setScalar(1)
      tempObj.updateMatrix()
      meshRef.current.setMatrixAt(i, tempObj.matrix)

      // Map fitness to color -- darken rejected candidates
      const colorStr = fitnessColor(c.fitnessScore) as string
      tempColor.set(colorStr)
      if (c.rejected) {
        tempColor.multiplyScalar(REJECTED_OPACITY / ACTIVE_OPACITY)
      }
      meshRef.current.setColorAt(i, tempColor)
    }

    meshRef.current.count = count
    meshRef.current.instanceMatrix.needsUpdate = true
    if (meshRef.current.instanceColor) {
      meshRef.current.instanceColor.needsUpdate = true
    }
  }, [candidates, islandLayouts, offsets, tempObj, tempColor])

  if (candidates.length === 0) return null

  return (
    <instancedMesh
      ref={meshRef}
      args={[undefined, undefined, Math.min(candidates.length, MAX_PARTICLES)]}
      key={candidates.length}
    >
      <sphereGeometry args={[0.08, 12, 12]} />
      <meshPhysicalMaterial
        vertexColors
        emissive="#ffffff"
        emissiveIntensity={0.15}
        roughness={0.5}
        metalness={0.0}
      />
    </instancedMesh>
  )
}

// ---------------------------------------------------------------------------
// Candidate Hit Targets (invisible per-candidate spheres for raycasting hover)
// ---------------------------------------------------------------------------
function CandidateHitTargets({
  candidates,
  islandLayouts,
  offsets,
  onHover,
  onUnhover,
}: {
  candidates: CandidateData[]
  islandLayouts: IslandLayout[]
  offsets: [number, number, number][]
  onHover: (candidateId: string, event: React.PointerEvent) => void
  onUnhover: () => void
}) {
  const count = Math.min(candidates.length, MAX_PARTICLES)
  return (
    <>
      {Array.from({ length: count }, (_, i) => {
        const c = candidates[i]
        const layout = islandLayouts[c.island] ?? islandLayouts[0]
        if (!layout) return null
        const [ox, oy, oz] = offsets[i]
        return (
          <mesh
            key={c.candidateId}
            position={[layout.position[0] + ox, layout.position[1] + oy, layout.position[2] + oz]}
            onPointerOver={(e) => { e.stopPropagation(); onHover(c.candidateId, e as unknown as React.PointerEvent) }}
            onPointerOut={onUnhover}
            visible={false}
          >
            <sphereGeometry args={[0.12, 8, 8]} />
            <meshBasicMaterial transparent opacity={0} />
          </mesh>
        )
      })}
    </>
  )
}

// ---------------------------------------------------------------------------
// Migration Stream sub-component (tube trail with traveling glow particle)
// ---------------------------------------------------------------------------
function MigrationStream({
  from,
  to,
}: {
  from: THREE.Vector3
  to: THREE.Vector3
}) {
  const tubeMatRef = useRef<THREE.MeshBasicMaterial>(null!)
  const glowRef = useRef<THREE.Mesh>(null!)
  const tRef = useRef(0)

  // Build a gentle arc between from and to via a lifted midpoint
  const curve = useMemo(() => {
    const mid = new THREE.Vector3().addVectors(from, to).multiplyScalar(0.5)
    mid.y += 0.8 // lift midpoint for arc
    return new THREE.CatmullRomCurve3([from, mid, to])
  }, [from, to])

  const tubeGeometry = useMemo(
    () => new THREE.TubeGeometry(curve, 20, 0.03, 6, false),
    [curve],
  )

  useFrame((_, delta) => {
    // Animate tube opacity: oscillate between 0.3 and 0.8
    if (tubeMatRef.current) {
      const elapsed = performance.now() * 0.001
      tubeMatRef.current.opacity = 0.55 + 0.25 * Math.sin(elapsed * Math.PI) // ~2s period
    }
    // Advance glow particle along the curve
    if (glowRef.current) {
      tRef.current = (tRef.current + delta * 0.4) % 1
      const pt = curve.getPointAt(tRef.current)
      glowRef.current.position.copy(pt)
    }
  })

  return (
    <group>
      {/* Tube trail */}
      <mesh geometry={tubeGeometry}>
        <meshBasicMaterial
          ref={tubeMatRef}
          color="#3b82f6"
          transparent
          opacity={0.55}
        />
      </mesh>

      {/* Traveling glow particle */}
      <mesh ref={glowRef}>
        <sphereGeometry args={[0.06, 10, 10]} />
        <meshBasicMaterial
          color={[0.3, 0.6, 2.0] as unknown as THREE.ColorRepresentation}
          toneMapped={false}
          transparent
          opacity={0.9}
        />
      </mesh>
    </group>
  )
}

// ---------------------------------------------------------------------------
// Migration Streams container
// ---------------------------------------------------------------------------
function MigrationStreams({
  migrations,
  islandLayouts,
}: {
  migrations: MigrationData[]
  islandLayouts: IslandLayout[]
}) {
  // Compute island pairs for migration streams
  const islandPairs = useMemo(() => {
    if (islandLayouts.length < 2) return []
    const pairs: Array<{ from: THREE.Vector3; to: THREE.Vector3; key: string }> = []
    for (let i = 0; i < islandLayouts.length; i++) {
      for (let j = i + 1; j < islandLayouts.length; j++) {
        const fromPos = islandLayouts[i].position
        const toPos = islandLayouts[j].position
        pairs.push({
          from: new THREE.Vector3(...fromPos),
          to: new THREE.Vector3(...toPos),
          key: `migration-${i}-${j}`,
        })
      }
    }
    return pairs
  }, [islandLayouts])

  // Only show streams for recent migrations (within last 5 seconds)
  const [hasRecentMigrations, setHasRecentMigrations] = useState(false)
  useEffect(() => {
    const check = () => {
      const now = Date.now()
      setHasRecentMigrations(migrations.some((m) => {
        const mTime = new Date(m.timestamp).getTime()
        return now - mTime < 5000
      }))
    }
    check()
    const timer = setInterval(check, 1000)
    return () => clearInterval(timer)
  }, [migrations])
  const activePairs = hasRecentMigrations ? islandPairs : []

  return (
    <>
      {activePairs.map((pair) => (
        <MigrationStream key={pair.key} from={pair.from} to={pair.to} />
      ))}
    </>
  )
}

// ---------------------------------------------------------------------------
// Ambient Particles sub-component (atmospheric floating dots)
// ---------------------------------------------------------------------------
const AMBIENT_PARTICLE_COUNT = 70

function AmbientParticles() {
  const meshRef = useRef<THREE.InstancedMesh>(null!)
  const tempObj = useMemo(() => new THREE.Object3D(), [])

  // Pre-compute initial positions and phase offsets (seeded by index)
  const { positions, phases } = useMemo(() => {
    const RADIUS = 12
    const pos = new Float32Array(AMBIENT_PARTICLE_COUNT * 3)
    const ph = new Float32Array(AMBIENT_PARTICLE_COUNT * 3) // phase offsets for x, y, z oscillation
    for (let i = 0; i < AMBIENT_PARTICLE_COUNT; i++) {
      // Deterministic distribution using golden-ratio spherical spread
      const y = 1 - (i / (AMBIENT_PARTICLE_COUNT - 1)) * 2 // -1 to 1
      const radiusAtY = Math.sqrt(1 - y * y)
      const theta = ((i * 2.399963) % (2 * Math.PI)) // golden angle
      pos[i * 3] = Math.cos(theta) * radiusAtY * RADIUS
      pos[i * 3 + 1] = y * RADIUS
      pos[i * 3 + 2] = Math.sin(theta) * radiusAtY * RADIUS
      // Unique phase offsets per axis per particle
      ph[i * 3] = i * 0.7
      ph[i * 3 + 1] = i * 1.1
      ph[i * 3 + 2] = i * 0.9
    }
    return { positions: pos, phases: ph }
  }, [])

  useFrame(({ clock }) => {
    if (!meshRef.current || typeof meshRef.current.setMatrixAt !== 'function') return
    const t = clock.elapsedTime * 0.15 // slow drift speed
    for (let i = 0; i < AMBIENT_PARTICLE_COUNT; i++) {
      const ix = i * 3
      tempObj.position.set(
        positions[ix] + Math.sin(t + phases[ix]) * 0.3,
        positions[ix + 1] + Math.cos(t + phases[ix + 1]) * 0.3,
        positions[ix + 2] + Math.sin(t + phases[ix + 2]) * 0.25,
      )
      tempObj.scale.setScalar(1)
      tempObj.updateMatrix()
      meshRef.current.setMatrixAt(i, tempObj.matrix)
    }
    meshRef.current.instanceMatrix.needsUpdate = true
  })

  return (
    <instancedMesh
      ref={meshRef}
      args={[undefined, undefined, AMBIENT_PARTICLE_COUNT]}
    >
      <sphereGeometry args={[0.025, 6, 6]} />
      <meshBasicMaterial color="#64748b" transparent opacity={0.4} />
    </instancedMesh>
  )
}

// ---------------------------------------------------------------------------
// Inner scene component (always called with hooks, no conditional returns)
// ---------------------------------------------------------------------------
function Islands3DScene({
  candidates,
  migrations,
  islandCount,
  lineageEvents,
}: Omit<Islands3DProps, 'seedFitness'>) {
  const { t } = useTranslation()
  const containerRef = useRef<HTMLDivElement>(null)
  const islandLayouts = useMemo(() => computeIslandLayout(islandCount), [islandCount])
  const [containerDims, setContainerDims] = useState({ width: 800, height: 500 })

  // Track container dimensions for DiffPopover positioning
  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    const ro = new ResizeObserver(() => {
      setContainerDims({ width: el.clientWidth, height: el.clientHeight })
    })
    ro.observe(el)
    setContainerDims({ width: el.clientWidth, height: el.clientHeight })
    return () => ro.disconnect()
  }, [])

  // Lifted offsets: shared between CandidateParticles and CandidateHitTargets
  const candidateOffsets = useMemo(() =>
    candidates.slice(0, MAX_PARTICLES).map(() => randomPointInSphere(ISLAND_RADIUS * 0.85)),
    [candidates],
  )

  // DiffPopover hover state (300ms delay)
  const hoverTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const [hoverTarget, setHoverTarget] = useState<{
    candidateId: string; x: number; y: number
  } | null>(null)

  // Build lineage index for DiffPopover
  const lineageIndex = useMemo(() => {
    const map = new Map<string, LineageNode>()
    if (lineageEvents) {
      for (const e of lineageEvents) map.set(e.candidateId, e)
    }
    return map
  }, [lineageEvents])

  // Clean up hover timer on unmount
  useEffect(() => {
    return () => { if (hoverTimerRef.current) clearTimeout(hoverTimerRef.current) }
  }, [])

  const handleCandidateHover = useCallback((candidateId: string, event: React.PointerEvent) => {
    if (hoverTimerRef.current) clearTimeout(hoverTimerRef.current)
    const container = containerRef.current
    if (container && lineageEvents && lineageIndex.has(candidateId)) {
      const rect = container.getBoundingClientRect()
      const x = (event.clientX ?? event.nativeEvent?.clientX ?? 0) - rect.left
      const y = (event.clientY ?? event.nativeEvent?.clientY ?? 0) - rect.top
      hoverTimerRef.current = setTimeout(() => {
        setHoverTarget({ candidateId, x, y })
      }, 300)
    }
  }, [lineageEvents, lineageIndex])

  const handleCandidateUnhover = useCallback(() => {
    if (hoverTimerRef.current) clearTimeout(hoverTimerRef.current)
    setHoverTarget(null)
  }, [])

  // Compute best fitness per island
  const bestFitnessPerIsland = useMemo(() => {
    const map = new Map<number, number>()
    for (let i = 0; i < islandCount; i++) {
      map.set(i, FITNESS_DOMAIN_MIN)
    }
    for (const c of candidates) {
      const current = map.get(c.island) ?? FITNESS_DOMAIN_MIN
      if (c.fitnessScore > current) {
        map.set(c.island, c.fitnessScore)
      }
    }
    return map
  }, [candidates, islandCount])

  // Compute candidate count per island for ripple triggers
  const candidateCountPerIsland = useMemo(() => {
    const map = new Map<number, number>()
    for (const c of candidates) {
      map.set(c.island, (map.get(c.island) ?? 0) + 1)
    }
    return map
  }, [candidates])

  // Track previous counts to detect new candidate arrivals
  const prevCountsRef = useRef<Map<number, number>>(new Map())
  const [rippleTriggers, setRippleTriggers] = useState<Map<number, number>>(new Map())

  useEffect(() => {
    const prev = prevCountsRef.current
    let changed = false
    const newTriggers = new Map(rippleTriggers)

    for (const [island, count] of candidateCountPerIsland) {
      const prevCount = prev.get(island) ?? 0
      if (count > prevCount) {
        newTriggers.set(island, (newTriggers.get(island) ?? 0) + 1)
        changed = true
      }
    }

    prevCountsRef.current = new Map(candidateCountPerIsland)
    if (changed) {
      setRippleTriggers(newTriggers)
    }
  }, [candidateCountPerIsland]) // eslint-disable-line react-hooks/exhaustive-deps

  const isEmpty = candidates.length === 0 && islandCount === 0

  return (
    <div ref={containerRef} className="bg-slate-800 border border-slate-700 rounded-lg p-4 h-[500px] relative">
      {isEmpty && (
        <div className="absolute inset-0 flex items-center justify-center z-10 pointer-events-none">
          <p className="text-slate-400">{t('evolution.noIslandDataToDisplay')}</p>
        </div>
      )}
      <Canvas camera={{ position: [0, 0, 15], fov: 50 }}>
        {/* Three-point lighting: ambient fill + directional key + point fill + cool rim */}
        <ambientLight intensity={0.3} />
        <directionalLight position={[8, 10, 5]} intensity={1.2} />
        <pointLight position={[10, 10, 10]} intensity={0.6} />
        <pointLight position={[-8, -5, -10]} intensity={0.3} color="#4488ff" />
        <OrbitControls enableDamping autoRotate autoRotateSpeed={0.4} />

        {/* Island particle fields (orbiting fitness-reactive particles) */}
        {islandLayouts.map((layout) => (
          <IslandParticleField
            key={`field-${layout.index}`}
            layout={layout}
            bestFitness={bestFitnessPerIsland.get(layout.index) ?? FITNESS_DOMAIN_MIN}
          />
        ))}

        {/* Island translucent spheres */}
        {islandLayouts.map((layout) => (
          <IslandSphere key={layout.index} layout={layout} />
        ))}

        {/* Ripple effects (pulse ring on new candidate arrival) */}
        {islandLayouts.map((layout) => (
          <RippleEffect
            key={`ripple-${layout.index}`}
            position={layout.position}
            color={layout.color}
            trigger={rippleTriggers.get(layout.index) ?? 0}
          />
        ))}

        {/* Candidate particles */}
        <CandidateParticles
          candidates={candidates}
          islandLayouts={islandLayouts}
          offsets={candidateOffsets}
        />

        {/* Invisible hit targets for per-candidate hover (DiffPopover) */}
        <CandidateHitTargets
          candidates={candidates}
          islandLayouts={islandLayouts}
          offsets={candidateOffsets}
          onHover={handleCandidateHover}
          onUnhover={handleCandidateUnhover}
        />

        {/* Migration streams */}
        <MigrationStreams
          migrations={migrations}
          islandLayouts={islandLayouts}
        />

        {/* Ambient floating particles */}
        <AmbientParticles />
      </Canvas>

      {/* DiffPopover overlay (appears after 300ms hover) */}
      {hoverTarget && lineageEvents && lineageEvents.length > 0 && (
        <DiffPopover
          candidateId={hoverTarget.candidateId}
          x={hoverTarget.x}
          y={hoverTarget.y}
          containerWidth={containerDims.width}
          containerHeight={containerDims.height}
          lineageIndex={lineageIndex}
        />
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main Islands3D component (exported) -- WebGL gate before hooks
// ---------------------------------------------------------------------------
export default function Islands3D({
  candidates,
  migrations,
  islandCount,
  lineageEvents,
}: Islands3DProps) {
  if (!isWebGLAvailable()) {
    return (
      <div className="flex items-center justify-center h-[500px] bg-slate-800 border border-slate-700 rounded-lg">
        <p className="text-slate-400">
          WebGL is not supported in your browser. Use the 2D view instead.
        </p>
      </div>
    )
  }

  return (
    <CanvasErrorBoundary>
      <Islands3DScene
        candidates={candidates}
        migrations={migrations}
        islandCount={islandCount}
        lineageEvents={lineageEvents}
      />
    </CanvasErrorBoundary>
  )
}

// The network in 3D: layers from front to back, every neuron a sphere sized by how strongly it
// fires, the strongest connections as lines, the circuit as red tubes with pulses flowing from
// the inputs to the decision, the backup route as brass tubes. Drag to turn it; hover a neuron
// to read it; click a hidden neuron to switch it off, on both devices.
import { useEffect, useRef } from 'react'
import * as THREE from 'three'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'

import type { Net } from '../model/net'
import type { Trace } from '../model/trace'

const SEAL = new THREE.Color('#ff4d64')
const BRASS = new THREE.Color('#e3a21a')
const IDLE = new THREE.Color('#5c6b8f')
const PUSH = new THREE.Color('#e88a9a')
const AGAINST = new THREE.Color('#7f9be0')
const LAYER_GAP = 9

interface Props {
  net: Net
  trace: Trace
  off: ReadonlySet<string>
  onToggle: (id: string) => void
}

interface Scene {
  renderer: THREE.WebGLRenderer
  scene: THREE.Scene
  camera: THREE.PerspectiveCamera
  controls: OrbitControls
  dynamic: THREE.Group // rebuilt for each trace
  pulses: { mesh: THREE.Mesh; from: THREE.Vector3; to: THREE.Vector3; phase: number }[]
  spheres: THREE.Mesh[]
  positions: Map<string, THREE.Vector3>
}

// Where each neuron sits: inputs and outputs as columns, hidden layers as square grids.
function layout(net: Net): Map<string, THREE.Vector3> {
  const depth = net.sizes.length - 1
  const pos = new Map<string, THREE.Vector3>()
  net.sizes.forEach((n, layer) => {
    const x = (layer - depth / 2) * LAYER_GAP
    const id = (i: number) => (layer === 0 ? `x${i}` : layer === depth ? `y${i}` : `h${layer}_${i}`)
    if (layer === 0 || layer === depth) {
      const gap = layer === 0 ? 1.45 : 2.6
      for (let i = 0; i < n; i++) pos.set(id(i), new THREE.Vector3(x, ((n - 1) / 2 - i) * gap, 0))
    } else {
      const cols = Math.ceil(Math.sqrt(n))
      const rows = Math.ceil(n / cols)
      for (let i = 0; i < n; i++) {
        const r = Math.floor(i / cols)
        const c = i % cols
        pos.set(id(i), new THREE.Vector3(x, ((rows - 1) / 2 - r) * 2.6, (c - (cols - 1) / 2) * 2.6))
      }
    }
  })
  return pos
}

export function Network3D({ net, trace, off, onToggle }: Props) {
  const host = useRef<HTMLDivElement>(null)
  const labels = useRef<HTMLDivElement>(null)
  const tip = useRef<HTMLDivElement>(null)
  const state = useRef<Scene | null>(null)
  const toggle = useRef(onToggle)
  toggle.current = onToggle

  // The scene, built once per network.
  useEffect(() => {
    const el = host.current
    if (!el) return
    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true,
      preserveDrawingBuffer: true })
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
    el.prepend(renderer.domElement)
    const scene = new THREE.Scene()
    scene.fog = new THREE.Fog(0x111827, 40, 90)
    const camera = new THREE.PerspectiveCamera(42, 1, 0.1, 200)
    camera.position.set(-18, 12, 34)
    const controls = new OrbitControls(camera, renderer.domElement)
    controls.enableDamping = true
    controls.autoRotate = true
    controls.autoRotateSpeed = 0.5
    controls.minDistance = 15
    controls.maxDistance = 70
    scene.add(new THREE.AmbientLight(0xffffff, 0.55))
    const sun = new THREE.DirectionalLight(0xffffff, 1.2)
    sun.position.set(10, 20, 15)
    scene.add(sun)
    const dynamic = new THREE.Group()
    scene.add(dynamic)
    const s: Scene = { renderer, scene, camera, controls, dynamic, pulses: [], spheres: [],
      positions: layout(net) }
    state.current = s

    const resize = () => {
      const w = el.clientWidth
      const h = el.clientHeight
      renderer.setSize(w, h, false)
      camera.aspect = w / Math.max(h, 1)
      camera.updateProjectionMatrix()
    }
    const observer = new ResizeObserver(resize)
    observer.observe(el)
    resize()

    // Hover to read a neuron, click to switch it off.
    const ray = new THREE.Raycaster()
    const pointer = new THREE.Vector2()
    let down = { x: 0, y: 0 }
    const pick = (e: PointerEvent) => {
      const r = renderer.domElement.getBoundingClientRect()
      pointer.set(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1)
      ray.setFromCamera(pointer, camera)
      return ray.intersectObjects(s.spheres)[0]?.object as THREE.Mesh | undefined
    }
    const move = (e: PointerEvent) => {
      const hit = pick(e)
      const t = tip.current
      renderer.domElement.style.cursor = hit?.userData.id?.startsWith('h') ? 'pointer' : ''
      if (!t) return
      if (hit) {
        const r = el.getBoundingClientRect()
        t.textContent = hit.userData.tip
        t.style.left = `${e.clientX - r.left + 14}px`
        t.style.top = `${e.clientY - r.top + 10}px`
        t.hidden = false
      } else t.hidden = true
    }
    const pressed = (e: PointerEvent) => { down = { x: e.clientX, y: e.clientY } }
    const click = (e: PointerEvent) => {
      if (Math.hypot(e.clientX - down.x, e.clientY - down.y) > 5) return // that was a drag
      const id = pick(e)?.userData.id as string | undefined
      if (id?.startsWith('h')) toggle.current(id)
    }
    renderer.domElement.addEventListener('pointermove', move)
    renderer.domElement.addEventListener('pointerdown', pressed)
    renderer.domElement.addEventListener('pointerup', click)

    let raf = 0
    const clock = new THREE.Clock()
    const frame = () => {
      const t = clock.getElapsedTime()
      for (const p of s.pulses) {
        const k = (t * 0.9 + p.phase) % 1
        p.mesh.position.lerpVectors(p.from, p.to, k)
        ;(p.mesh.material as THREE.MeshBasicMaterial).opacity = Math.sin(k * Math.PI)
      }
      controls.update()
      renderer.render(scene, camera)
      placeLabels(s, labels.current, el)
      raf = requestAnimationFrame(frame)
    }
    raf = requestAnimationFrame(frame)
    return () => {
      cancelAnimationFrame(raf)
      observer.disconnect()
      controls.dispose()
      renderer.dispose()
      renderer.domElement.remove()
      state.current = null
    }
  }, [net])

  // The trace: rebuilt whenever the decision, the circuit or the switched-off neurons change.
  useEffect(() => {
    const s = state.current
    if (!s) return
    build(s, net, trace, off)
    writeLabels(labels.current, net, trace)
  }, [net, trace, off])

  return (
    <div ref={host} className="net3d">
      <div ref={labels} className="net3d-labels" aria-hidden="true" />
      <div ref={tip} className="net3d-tip" hidden />
      <p className="net3d-hint">Drag to turn. Hover a neuron to read it; click one to switch it off.</p>
    </div>
  )
}

function build(s: Scene, net: Net, trace: Trace, off: ReadonlySet<string>) {
  for (const child of [...s.dynamic.children]) {
    s.dynamic.remove(child)
    child.traverse((o) => {
      const m = o as THREE.Mesh
      m.geometry?.dispose()
      ;(m.material as THREE.Material | undefined)?.dispose?.()
    })
  }
  s.pulses = []
  s.spheres = []
  const depth = net.sizes.length - 1
  const circuit = new Set(trace.circuit?.hidden ?? [])
  const backup = new Set(trace.backup?.hidden ?? [])
  const usedInputs = new Set(trace.circuit?.nodes.filter((n) => n.startsWith('x')) ?? [])
  const backupInputs = new Set(trace.backup?.nodes.filter((n) => n.startsWith('x')) ?? [])
  const label = (id: string) => net.neurons.find((n) => n.id === id)?.label ?? id

  // Neurons.
  const sphere = new THREE.SphereGeometry(1, 24, 16)
  net.sizes.forEach((n, layer) => {
    const acts = trace.run.acts[layer]
    const max = Math.max(1e-6, ...acts.map(Math.abs))
    for (let i = 0; i < n; i++) {
      const id = layer === 0 ? `x${i}` : layer === depth ? `y${i}` : `h${layer}_${i}`
      const a = acts[i]
      const isOff = off.has(id)
      const strength = layer === depth ? trace.run.probs[i] : Math.max(0, a) / max
      let color = IDLE
      if (circuit.has(id) || usedInputs.has(id) || (layer === depth && i === trace.choice)) color = SEAL
      else if (backup.has(id) || backupInputs.has(id)) color = BRASS
      const mat = new THREE.MeshStandardMaterial({
        color: isOff ? new THREE.Color('#2a2f3a') : color,
        emissive: isOff ? new THREE.Color('#000000') : color,
        emissiveIntensity: isOff ? 0 : 0.15 + 0.85 * strength,
        roughness: 0.35, metalness: 0.1, transparent: isOff, opacity: isOff ? 0.5 : 1,
      })
      const mesh = new THREE.Mesh(sphere, mat)
      const r = layer === depth ? 0.55 + 0.6 * strength : 0.3 + 0.55 * strength
      mesh.scale.setScalar(r)
      mesh.position.copy(s.positions.get(id)!)
      const name = layer === 0 ? net.inputs[i].label : layer === depth ? net.outputs[i].label : label(id)
      mesh.userData = { id, tip: `${name}${isOff ? ' (switched off)' : ''}: ${layer === depth
        ? `${Math.round(trace.run.probs[i] * 100)}%` : a.toFixed(2)}` }
      s.dynamic.add(mesh)
      s.spheres.push(mesh)
      if (isOff) {
        const cross = new THREE.Mesh(new THREE.TorusGeometry(r * 1.5, 0.06, 6, 24),
          new THREE.MeshBasicMaterial({ color: SEAL }))
        cross.position.copy(mesh.position)
        cross.rotation.y = Math.PI / 2
        s.dynamic.add(cross)
      }
    }
  })

  // The strongest connections, as thin lines coloured by which way they push.
  const attrs = Object.entries(trace.edgeAttr).filter(([, a]) => Math.abs(a) > 1e-9)
  const max = Math.max(1e-9, ...attrs.map(([, a]) => Math.abs(a)))
  const strong = attrs.filter(([, a]) => Math.abs(a) > max * 0.05)
    .sort((a, b) => Math.abs(b[1]) - Math.abs(a[1])).slice(0, 90)
  const pts: number[] = []
  const cols: number[] = []
  const ends = (e: string) => {
    const [l, i, j] = e.split(':').map(Number)
    const a = l === 0 ? `x${i}` : `h${l}_${i}`
    const b = l + 1 === depth ? `y${j}` : `h${l + 1}_${j}`
    return [s.positions.get(a)!, s.positions.get(b)!]
  }
  for (const [e, a] of strong) {
    const [p, q] = ends(e)
    const c = (a > 0 ? PUSH : AGAINST).clone().multiplyScalar(0.35 + 0.65 * Math.abs(a) / max)
    pts.push(p.x, p.y, p.z, q.x, q.y, q.z)
    cols.push(c.r, c.g, c.b, c.r, c.g, c.b)
  }
  const lines = new THREE.BufferGeometry()
  lines.setAttribute('position', new THREE.Float32BufferAttribute(pts, 3))
  lines.setAttribute('color', new THREE.Float32BufferAttribute(cols, 3))
  s.dynamic.add(new THREE.LineSegments(lines, new THREE.LineBasicMaterial({ vertexColors: true,
    transparent: true, opacity: 0.55 })))

  // The circuit and the backup route, as tubes; pulses run along the circuit.
  const tubes = (edges: string[], color: THREE.Color, radius: number, pulse: boolean) => {
    for (const e of edges) {
      const [p, q] = ends(e)
      const tube = new THREE.Mesh(new THREE.TubeGeometry(new THREE.LineCurve3(p, q), 1, radius, 6),
        new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.85 }))
      s.dynamic.add(tube)
      if (pulse) {
        const dot = new THREE.Mesh(new THREE.SphereGeometry(0.22, 10, 8),
          new THREE.MeshBasicMaterial({ color: '#ffffff', transparent: true }))
        s.dynamic.add(dot)
        s.pulses.push({ mesh: dot, from: p, to: q, phase: -Number(e.split(':')[0]) * 0.33 + 3 })
      }
    }
  }
  tubes(trace.backup?.edges ?? [], BRASS, 0.07, false)
  tubes(trace.circuit?.edges ?? [], SEAL, 0.1, true)
}

// Names next to the inputs, the outputs and the circuit's neurons.
function writeLabels(el: HTMLDivElement | null, net: Net, trace: Trace) {
  if (!el) return
  const used = new Set([...(trace.circuit?.nodes ?? []), ...(trace.backup?.nodes ?? [])])
  const items: { id: string; text: string; cls: string }[] = []
  net.inputs.forEach((f, i) => items.push({ id: `x${i}`, text: f.label,
    cls: `in${used.has(`x${i}`) ? ' on' : ''}` }))
  net.outputs.forEach((o, k) => items.push({ id: `y${k}`,
    text: `${o.label} ${Math.round(trace.run.probs[k] * 100)}%`, cls: `out${k === trace.choice ? ' on' : ''}` }))
  for (const id of trace.circuit?.hidden ?? []) {
    const n = net.neurons.find((x) => x.id === id)
    if (n) items.push({ id, text: n.label, cls: 'hid on' })
  }
  el.replaceChildren(...items.map((it) => {
    const d = document.createElement('div')
    d.className = `net3d-label ${it.cls}`
    d.textContent = it.text
    d.dataset.id = it.id
    return d
  }))
}

function placeLabels(s: Scene, el: HTMLDivElement | null, host: HTMLElement) {
  if (!el) return
  const w = host.clientWidth
  const h = host.clientHeight
  const v = new THREE.Vector3()
  for (const d of el.children as HTMLCollectionOf<HTMLElement>) {
    const p = s.positions.get(d.dataset.id ?? '')
    if (!p) continue
    v.copy(p).project(s.camera)
    const behind = v.z > 1
    d.style.transform = `translate(${((v.x + 1) / 2) * w}px, ${((1 - v.y) / 2) * h}px)`
    d.style.opacity = behind ? '0' : ''
  }
}

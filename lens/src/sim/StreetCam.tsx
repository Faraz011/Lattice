// The car's camera as Google Street View: the real photo of the street where the car is, facing
// its direction of travel. Between two panoramas the camera glides forward inside the current
// one, then the next one fades in, so driving reads as motion through real streets. The
// simulation's own traffic lights, pedestrians and cars are drawn as labelled markers over the
// photo, from their positions on the route; the people and cars in the photo itself are real
// and play no part in the simulation.
import { useEffect, useRef, useState, type RefObject } from 'react'
import * as THREE from 'three'

import { between, type Colour, type Physics, type RouteMap, type World } from './driving'
import { offset, poseAt } from './geo'
import { drawBoxes, seen, type Box } from './perception'
import { patchFor, PanoTrack, type Pano, type Patch } from './streetview'

const VFOV = 52 // vertical field of view, degrees: about 80 across a 16:9 screen
const PITCH = -4 // a dashcam looks slightly down the road
const CAMERA_HEIGHT = 2.5 // Street View cameras ride about 2.5 m up
const LANE = -1.9

interface Props {
  world: RefObject<World>
  map: RouteMap
  forced: RefObject<Map<number, Colour>>
  tick: number
  physics: Physics
  rear: boolean
  onFail: (why: string) => void
}

interface Layer {
  pano: Pano
  patch: Patch
  scene: THREE.Scene
  material: THREE.MeshBasicMaterial
  texture: THREE.CanvasTexture
  dispose: () => void
}

export function StreetCam({ world, map, forced, tick, physics, rear, onFail }: Props) {
  const host = useRef<HTMLDivElement>(null)
  const boxes = useRef<HTMLDivElement>(null)
  const [credit, setCredit] = useState('© Google')
  const back = useRef(rear)
  back.current = rear
  const failed = useRef(onFail)
  failed.current = onFail

  useEffect(() => {
    const el = host.current
    if (!el) return
    const track = new PanoTrack(map)
    const renderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true })
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
    renderer.autoClear = false
    el.prepend(renderer.domElement)
    const camA = new THREE.PerspectiveCamera(VFOV, 1, 0.1, 100)
    const camB = camA.clone()
    const layers = new Map<string, Layer>()
    let raf = 0
    let alive = true
    let bearing = 0
    let lastCredit = ''
    let last = performance.now()

    const resize = () => {
      renderer.setSize(el.clientWidth, el.clientHeight, false)
      for (const c of [camA, camB]) {
        c.aspect = el.clientWidth / Math.max(el.clientHeight, 1)
        c.updateProjectionMatrix()
      }
    }
    const observer = new ResizeObserver(resize)
    observer.observe(el)
    resize()

    // A panorama's visible patch, painted tile by tile onto the inside of a sphere segment.
    const build = (pano: Pano, view: number): Layer => {
      const patch = patchFor(pano, view, 75)
      const canvas = document.createElement('canvas')
      canvas.width = patch.cols.length * pano.tile
      canvas.height = patch.rows.length * pano.tile
      const g = canvas.getContext('2d')!
      g.fillStyle = '#7f8a99'
      g.fillRect(0, 0, canvas.width, canvas.height)
      const texture = new THREE.CanvasTexture(canvas)
      texture.colorSpace = THREE.SRGBColorSpace
      const rad = Math.PI / 180
      const geometry = new THREE.SphereGeometry(10, 64, 32, (patch.startBearing - 90) * rad,
        patch.spanDeg * rad, patch.topDeg * rad, patch.heightDeg * rad)
      geometry.scale(-1, 1, 1) // seen from inside
      const material = new THREE.MeshBasicMaterial({ map: texture, transparent: true, opacity: 1,
        depthWrite: false })
      const scene = new THREE.Scene()
      scene.add(new THREE.Mesh(geometry, material))
      let cancelled = false
      patch.cols.forEach((x, i) => patch.rows.forEach((y, j) => {
        const img = new Image()
        img.crossOrigin = 'anonymous'
        img.onload = () => {
          if (cancelled) return
          g.drawImage(img, i * pano.tile, j * pano.tile)
          texture.needsUpdate = true
        }
        img.src = track.tileUrl(pano, patch.zoom, x, y)
      }))
      return { pano, patch, scene, material, texture, dispose: () => {
        cancelled = true
        geometry.dispose()
        material.dispose()
        texture.dispose()
      } }
    }
    const layerFor = (pano: Pano, view: number): Layer => {
      const have = layers.get(pano.id)
      const off = have ? Math.abs(((view - (have.patch.startBearing + have.patch.spanDeg / 2)) + 540) % 360 - 180) : 0
      if (have && off < 30) return have
      have?.dispose()
      const fresh = build(pano, view)
      layers.set(pano.id, fresh)
      return fresh
    }

    const look = (cam: THREE.PerspectiveCamera, b: number, forward: number) => {
      const r = (b * Math.PI) / 180
      const p = (PITCH * Math.PI) / 180
      const dir = new THREE.Vector3(Math.sin(r) * Math.cos(p), Math.sin(p), -Math.cos(r) * Math.cos(p))
      cam.position.copy(dir.clone().setY(0).normalize().multiplyScalar(forward))
      cam.lookAt(cam.position.clone().add(dir))
    }

    track.start().then(() => {
      const poll = () => {
        if (!alive) return
        const w = world.current
        if (w) void track.ahead(w.car.at).then(() => {
          if (track.error && !track.panos.length) failed.current(track.error)
        })
        window.setTimeout(poll, 600)
      }
      poll()
    }).catch((e: Error) => failed.current(e.message))

    const frame = () => {
      raf = requestAnimationFrame(frame)
      const w = world.current
      if (!w) return
      const now = performance.now()
      const alpha = Math.min(1, (now - (w.tickAt ?? now)) / (tick * 1000))
      const carS = between(w.car.prev, w.car.at, alpha, w.length)
      const route = poseAt(map, carS, 14).bearing
      const turn = ((route - bearing + 540) % 360) - 180
      bearing = (bearing + turn * (1 - Math.exp(-Math.min(now - last, 500) / 220)) + 360) % 360
      last = now
      const rear = back.current
      const view = rear ? (bearing + 180) % 360 : bearing

      const { here, next } = track.around(carS)
      renderer.clear()
      if (here) {
        const L = map.length_m
        let gap = next ? next.s - here.s : 0
        if (gap <= 0) gap += L
        let into = carS - here.s
        if (into < 0) into += L
        const t = next && gap < 60 ? Math.min(1, into / gap) : 0
        const sign = rear ? -1 : 1
        // Glide forward inside this panorama; fade the next one in over the last third.
        const a = layerFor(here, view)
        a.material.opacity = 1
        look(camA, view, sign * 3.2 * t)
        renderer.render(a.scene, camA)
        if (next && next.id !== here.id && t > 0.66) {
          const b = layerFor(next, view)
          b.material.opacity = (t - 0.66) / 0.34
          look(camB, view, -sign * 1.6 * (1 - t))
          renderer.render(b.scene, camB)
        }
        for (const [id, layer] of layers) {
          if (id !== here.id && id !== next?.id) { layer.dispose(); layers.delete(id) }
        }
        const c = `${here.copyright}${here.date ? `, ${here.date}` : ''}`
        if (c !== lastCredit) { lastCredit = c; setCredit(c) }
      }

      // The simulation's objects, as markers on the photo.
      const W = el.clientWidth
      const H = el.clientHeight
      const f = (H / 2) / Math.tan((VFOV / 2) * (Math.PI / 180))
      const horizon = H / 2 - f * Math.tan((PITCH * Math.PI) / 180)
      const me = poseAt(map, carS, 6)
      const [cLng, cLat] = offset(me, 0, LANE)
      const found: Box[] = []
      for (const o of seen(w, physics, forced.current ?? undefined)) {
        const p = poseAt(map, o.s, 6)
        const [lng, lat] = offset(p, 0, o.right)
        const east = (lng - cLng) * 111_320 * Math.cos((cLat * Math.PI) / 180)
        const north = (lat - cLat) * 110_540
        const dist = Math.hypot(east, north)
        if (dist < 3) continue
        const rel = ((Math.atan2(east, north) * 180) / Math.PI - view + 540) % 360 - 180
        if (Math.abs(rel) > 50) continue
        const forward = dist * Math.cos((rel * Math.PI) / 180)
        const x = W / 2 + f * Math.tan((rel * Math.PI) / 180)
        const bottom = horizon + (f * (CAMERA_HEIGHT - o.base)) / forward
        const h = (f * o.height) / forward
        found.push({ key: o.key, kind: o.kind, x, y: bottom, w: (f * o.width) / forward, h,
          label: o.label, used: o.used })
      }
      drawBoxes(boxes.current, found)
    }
    raf = requestAnimationFrame(frame)

    return () => {
      alive = false
      cancelAnimationFrame(raf)
      observer.disconnect()
      for (const layer of layers.values()) layer.dispose()
      renderer.dispose()
      renderer.domElement.remove()
    }
  }, [world, map, forced, tick, physics])

  return (
    <div className="city-wrap">
      <div ref={host} className="city-map street" role="img"
        aria-label={`Google Street View from the car's ${rear ? 'rear' : 'front'} camera, ${map.name}`} />
      <div ref={boxes} className="perception sim-markers" aria-hidden="true" />
      <p className="street-credit"><strong>Google</strong> Street View · {credit} · markers:
        simulated objects</p>
    </div>
  )
}

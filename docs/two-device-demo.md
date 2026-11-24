# The two-device demo: watch a decision happen, and see inside it

One device runs the world. The other shows the neural network deciding what to do in it,
neuron by neuron, traced live. Switch a neuron off on the second device and the car or the bank
on the first one acts without it.

There are two scenarios, switched on device 1:

- **Self-driving car, in central London.** A 3D map with buildings; the car drives a 9.6 km loop
  through Westminster, the Strand and Waterloo Bridge, keeping left, past the traffic lights and
  pedestrian crossings OpenStreetMap has on those streets, with pedestrians and cars cutting in.
  A small network (13 inputs, 16 + 8 hidden neurons, 3 actions) drives: accelerate, cruise or
  brake. A blue fan ahead of the car shows the 120 m it can see.
- **Bank: money laundering, across Europe.** Two weeks of a bank, transfer by transfer. Accounts
  sit in their customers' cities (London, Paris, Frankfurt, Madrid and six more); transfers fly
  between them on the map; a live ledger lists each with names, masked IBANs, the amount in the
  sender's currency, the method (SWIFT wire, SEPA, Faster Payments, card, cash deposit, P2P,
  crypto) and its status. A small network (14 inputs read from each account's transaction
  neighbourhood, 10 + 8 hidden neurons) checks every account; an agent freezes an account once
  the check is 90% sure, and a frozen account's later transfers are blocked.

Device 2 shows, for whatever device 1 is deciding:

- a sentence a panel can read aloud ("It decides brake because of the traffic light. Without
  that, the crosswalk alone would still make it brake.") and a confidence gauge;
- the network in 3D: every neuron a sphere sized by how strongly it fires, the circuit as red
  tubes with pulses running to the decision, the backup route in brass. Drag to turn it, hover a
  neuron to read it, click one to switch it off. **Flat** shows the same in two dimensions;
- **What drove this decision**: each thing in the scene taken away in turn, and how much of the
  decision went with it;
- **How sure it has been**: the network's confidence in each choice, decision by decision;
- **What would change its mind**: the inputs that matter most as sliders and switches, in metres
  and km/h for the car. It re-decides on device 2 only; the simulation is not touched.

Both networks are trained here (`src/lattice/lens`) and run in the browser, so the circuit on
device 2 is the one that actually drives the decision on device 1.

## Setup

**Hosted (two devices anywhere).** Deploy once: in Render, New > Blueprint, this repository,
blueprint path `deploy/lens/render.yaml`. It is one free web service built from
`Dockerfile.lens`; it sleeps after 15 minutes idle, so open it a minute before you present.

**One laptop, or two devices on the same Wi-Fi.**

```bash
docker build -f Dockerfile.lens -t lattice-lens . && docker run --rm -p 8090:8090 lattice-lens
```

Open `http://<laptop-address>:8090` on both devices.

On device 1 choose **Open the simulation**; on device 2 enter the same room code and choose
**Open the trace** (or go straight to `/#/trace/<code>`). Both show **Paired**.

## Five minutes

1. **The car drives (30 s).** Device 1: past Parliament Square and up Whitehall, it accelerates
   to cruising speed, stops at red lights and waits for people at crossings. Device 2's sentence:
   *nothing here changes its mind*: on an empty road it does what it always does.
2. **A reason to brake (60 s).** Device 1: **Red light and a pedestrian**. The car stops and the
   world pauses itself at that moment. Device 2 reads: *It decides brake because of the traffic
   light.* The 3D network shows the route in red, pulses running to "brake"; **What drove this
   decision** gives the traffic light most of it. Drag the **Distance to the light** slider out
   to 60 m: *it would change its mind*.
3. **The backup route (60 s), the moment.** Device 2, dashed brass: **the crosswalk** is a
   second, separate reason to brake. "Reading the circuit alone, you would not know this route
   exists." Press **Switch off the detector it fires**. Device 1: resume. The car still holds:
   the pedestrian carries the decision. Device 2 re-traces: the crosswalk is now the circuit.
4. **Break it (45 s).** Switch everything back on, **Start a new drive**, then on device 2 click
   the red-light detectors off one by one (they are labelled). Without them the car runs red
   lights, and device 1 says so: *Ran a red light*.
5. **The bank (60 s).** Device 1: **Bank: money laundering**, Speed 3x. Transfers fly across
   Europe and fill the ledger. A two-route mule ring forms: large transfers through new accounts,
   forwarded within hours; the ledger marks them *Under review: layering*; the agent freezes the
   mules and their next transfers show *Blocked: sender frozen*. Device 2 traces the account the
   agent just acted on: the evidence (passes money on, forwards within a day, sits on a long
   forwarding chain) and the neurons that read it. Click any account, on the map or in the
   ledger, to trace it. Tick **Show the planted cases** to show that every
   frozen account was planted and no everyday account or decoy was touched.
6. **What it is (15 s).** The same search Lattice runs on transaction graphs (the evidence
   circuit, then the backup routes), applied to a neural network's own neurons.

## What to say if asked

- **These are real networks and real traces.** The weights are trained, exported and run as
  they are. Every circuit and backup claim is checked by running the network with the other
  neurons patched (activation patching); attribution only orders the search.
- **"Compared with" matters.** A decision is explained against a reference: the same moment on
  an empty road, or an average clear account. The circuit is what makes this decision differ
  from that one.
- **Evidence is taken away whole.** The tracer removes a thing from the scene (the traffic light:
  its colour and distance together), never a single input, so it never asks the network about a
  situation that cannot happen, such as a light with no colour.
- **Neuron names are read, not given.** Each hidden neuron is named after the driving concept or
  account feature it correlates with best over the training data. Some track two concepts and
  are named for both ("yellow light to stop for or red light ahead to stop for"): they are
  polysemantic, and the name says so.
- **The maps are real; the traffic is simulated.** Streets, buildings, signals and crossings come
  from OpenStreetMap; signal timings, pedestrians and other cars are the simulation's. The map
  tiles load from OpenFreeMap, so the hosted demo needs internet; without it the car and its
  street furniture still draw, on a blank background.
- **The networks are small on purpose.** 24 and 18 hidden neurons: small enough to draw every
  one and trace a decision in milliseconds. The driving network agrees with the rule-based
  expert it learned from 96.7% of the time on situations it never saw, and drove 50 simulated
  minutes without an incident; the account check is 99.1% correct on accounts from worlds it
  never saw.
- **Backup routes come from training.** The driving network was trained with dropout, which
  makes a network grow redundant routes to a decision: the phenomenon the research studies in
  language models.

## Rebuilding

```bash
uv run --group lens python -m lattice.lens.train                 # both networks and the episode
uv run python -m lattice.lens.city                               # the London route (online, once)
uv run --group lens python -m lattice.lens.train --only driving  # one of them
npm --prefix lens test                                           # the tracer and both worlds
```

For development, run the relay and the Vite server side by side (`.claude/launch.json` has both):

```bash
uv run python -m lattice.lens.relay --port 8090
npm --prefix lens run dev    # http://localhost:5180, reachable from the local network
```

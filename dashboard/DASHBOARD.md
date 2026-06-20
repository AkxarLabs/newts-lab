# Dashboard — Requirements & Model

This document defines **what the dashboard must do** — the features it must cover, the model of the
lab it must portray, and the reasons behind each. It is a feature/structure specification, not a
style guide: it deliberately says nothing about colours, palettes, specific character looks, or room
artwork. Those are implementation choices made elsewhere. Here we record only the *capabilities* the
dashboard must provide, the *workflow it must make visible*, and the *why* behind each.

The dashboard is **optional** (see §11.1), but where it exists it must satisfy everything below.

---

## 1. Purpose

The lab runs autonomous and semi-autonomous agents that take research ideas through a multi-stage
lifecycle. The dashboard exists so a human (the PI) can **watch that work happen and steer it**
without reading raw files or transcripts.

It must serve two jobs at once:

- **Observability** — at any moment, show what the lab is doing: which studies/projects exist, what
  stage each is in, what is running, and which agents are active.
- **Control** — let the PI act on what they see: command the lab, approve the human decision
  points, run read-only checks, and leave instructions.

**Why:** an autonomous lab that the human cannot see into or redirect is neither trustworthy nor
useful. The dashboard is the window *and* the steering wheel, so the PI stays in the loop while the
lab iterates.

---

## 2. The portfolio model — the world shows ALL work at once

This is the single most important thing to get right, because everything else hangs off it.

### 2.1 The lab is a portfolio, never a single project
The lab carries **many ideas and projects at the same time**, each at a *different* point in the
lifecycle. This is the normal state, not an edge case: the registry is a roster of many rows; the PI
can seed several directions at once; the unattended campaign mode runs multiple ideas in parallel;
and the back-half round-trips (§4) mean one project can be running experiments while a *different*
paper is in review. The dashboard must therefore represent and show **all ongoing (and terminal)
work simultaneously** — it is a portfolio view, never a one-thing-at-a-time pipeline.

**Why:** if the dashboard only showed one project, it would misrepresent the lab. The PI's core need
is to see the *whole* board — everything in flight, everywhere — in one place.

### 2.2 Two readings of the same map
The world and the lifecycle are the same structure read two ways, and the dashboard must support
both readings:

- **The lifecycle = one idea's *biography*** — the path a *single* idea walks *over time*
  (incubate → study → experiment → write → archive). This is the temporal view of one thing.
- **The world = a *census* of everyone *right now*** — a spatial snapshot of the *whole portfolio*
  frozen at this instant, where each idea/project sits in the place that matches **its own** current
  state. Nothing "walks the pipeline" on screen as a single token; instead **many entities occupy
  many places at once**, and each migrates from place to place on its own schedule as its state
  changes.

**Why:** the PI thinks both ways — "where is *this* project headed?" (biography) and "what is the
lab doing *as a whole* right now?" (census). The dashboard's spatial layout is the census; the
flowcharts in §4 are the biography. They must stay consistent with each other.

### 2.3 A representative snapshot
At any moment the world might be showing, all at once:

```
 INCUBATOR         2 fresh ideas + 1 just-triaged idea
 THE STUDY         idea-A grounding in literature · idea-B being scoped
 [GATE 1]          proposal-C waiting for the PI
 THE LAB           project-D running a full sweep · project-E being analyzed · project-F at GATE 2
 THE WRITING ROOM  paper-G under review (a reviewer ensemble is present)
 THE ARCHIVE       3 finished papers at rest
 THE MARGINS       2 killed · 1 parked
```

That single screen *is* the entire lab's state. Every entry above is a separate entity in its place,
each with its own workers. The dashboard's job is to make this readable at a glance.

### 2.4 Many projects coexist — and each is its own lab
Because several projects can be in the *same* stage at once (e.g. two projects both running
experiments), a single place may hold **multiple projects simultaneously**, each with its own cluster
of workers. The dashboard must:

- show them as **distinct entities sharing the place**, not merge them; and
- let the PI **drill into any one project** to see *that* project as its own isolated working space —
  its current workers operating — while the others keep running in the world behind it.

**Why:** "the lab" (the experiment stage) is really a collection of independent project labs running
side by side. The PI needs both the shared overview *and* the ability to focus on one project's
internal activity without losing the rest.

---

## 3. The world metaphor and its navigation

### 3.1 The whole lab is one continuous world
The lab must be presented as a **single connected world**, not disconnected charts or lists. The PI
should feel they are looking at one place that contains everything (the whole portfolio, per §2).

**Why:** the lab is one system; a unified world makes the relationships between its parts legible and
gives the PI a stable mental map.

### 3.2 Each part of the workflow is its own place (a "room") in the world
Every stage/phase of the research workflow must correspond to a distinct **place** in the world (we
call these *rooms*; see §4). Moving through the lifecycle is moving through the world; an entity's
*position* is its *status*.

**Why:** spatial separation lets the PI see *where in the process* any piece of work is, instantly,
just by where it sits.

### 3.3 Each room's environment reflects the workflow phase it represents
A room's surroundings must visibly evoke the phase it stands for, so the PI can make the **visual
connection** between a place and the activity that happens there.

**Why:** an environment that matches its phase turns the map into something self-explanatory — the PI
learns what each place means by looking at it.

### 3.4 The layout must be dense and organic, not a flat line
The rooms must be arranged **densely and non-linearly** — an interconnected, varied composition
rather than a single straight row of equal boxes.

**Why:** a dense, organic layout reads as a living place and uses space well; a flat strip feels
mechanical and wastes the screen. It also keeps rooms legible whether they hold zero entities or many
(§4 closing note).

### 3.5 Cinematic navigation between places
Changing the PI's focus from one part of the world to another must be a **smooth, cinematic
transition** — pulling back for context then pushing in to the destination (a zoom-out-then-zoom-in
motion), not a hard cut.

**Why:** the transition preserves the PI's sense of *where they went and why*, keeping the world
coherent as they move around it, and is part of making the experience feel alive.

### 3.6 Free navigation and drill-in
The PI must be able to roam the world freely (pan across it), zoom into any room for detail, drill
into a single project (§2.4), and always return to the overview via an explicit way back.

**Why:** the world is larger than one screen; the PI needs to move fluidly between the big picture and
the close-up without getting lost.

---

## 4. The rooms — the workflow stages and the processing inside each

The world is divided into **rooms, grouped by workflow phase**. A room is a *presentation grouping*
over the lab's underlying lifecycle states — collapsing the fine-grained states into a handful of
meaningful places keeps the world legible. **Changing how many rooms there are is purely a display
choice; it never changes the lab's actual lifecycle or protocol.** The exact sub-state of any entity
is always still available on the entity itself and in the Projects view (§8), so consolidating rooms
loses no information.

The model below uses **six rooms**. Two structural facts shape it:

- **Hub-side vs project-side:** the Incubator, Study, Writing Room and Archive are *hub-side* (idea
  and paper work). **The Lab is the external project repo** — entering it means entering/spawning a
  project; leaving it means returning results to the hub.
- **Gates are doorways, not rooms:** each human decision point (Gate 1, Gate 2, Gate 3) is the
  *threshold an entity must be let through to advance*, shown on the connection between rooms — not a
  room of its own.

There are also **two round-trips**: analysis can send a project back into experiments, and review can
send a project back to the lab for new experiments.

### Overall flow (rooms = places, gates = doors)

```
   THE MARGINS  ◄── park / kill is reachable from ANY room
   (parked, killed)

 INCUBATOR ──► THE STUDY ──[GATE 1]──► THE LAB ──────► THE WRITING ROOM ──[GATE 3]──► THE ARCHIVE
 (seed,       (lit-review,   human    (active +        (writing +           human     (final)
  triaged)     scoping,                analysis,        internal-review)
               proposal)               [GATE 2 inside])
                                           ▲                  │
                                           └──────────────────┘
                                         NEEDS-EXPERIMENT round-trip
```

Remember (§2.2): the diagram above is one idea's *journey*. In the live world, **all six rooms are
populated at once** by different entities, each at its own point on this path.

---

### 4.1 Incubator — *where ideas are born and sorted* (hub)
- **Covers lifecycle states:** `seed` (a raw idea just captured), `triaged` (kept, after a quick
  keep/park/kill sort).
- **What happens:** the ideation pipeline generates many candidate ideas, critiques them, evolves and
  combines the survivors, ranks them in a tournament, and triages the winners into idea folders.
- **An entity enters when:** the PI gives a direction, or the lab mines its own open questions.
  **Leaves when:** an idea is kept (→ the Study) or set aside (→ the Margins).
- **Who works here:** the orchestrator + an *ideation-critic* ensemble.

```
 direction / mine lab knowledge
        │
        ▼
 generate candidate ideas
        │
        ▼
 reflect: critic ensemble per idea ──► evolve ──► combine / crossover
        │
        ▼
 tournament rank
        │
        ▼
 triage ─┬─ keep → idea @ TRIAGED ──► THE STUDY
         ├─ park ─────────────────►  THE MARGINS
         └─ kill ─────────────────►  THE MARGINS
```

### 4.2 The Study — *shape the idea before spending compute* (hub)
- **Covers lifecycle states:** `lit-review`, `scoping`, `proposal`.
- **What happens:** ground the idea in the literature and render a **novelty verdict**; then enumerate
  every key design decision and argue each into an ADR-style record (flagging which decisions are
  *headline*); then write a full **proposal** — hypothesis, baselines, eval protocol, *staged*
  experiment plan, ablations, compute budget, **kill criteria**, success criteria. **Gate 1** is the
  door out of this room.
- **Enters when:** an idea is kept. **Leaves when:** Gate 1 approves it (→ The Lab), or it is
  parked/killed.
- **Who works here:** orchestrator, *fresh-context-reviewer* (nested critique on load-bearing papers),
  *scoping-advocate* ensemble.

```
 idea @ triaged
   │
   ▼
 LIT-REVIEW: search → per-paper notes → (nested critique on key papers)
   │
   ▼
 novelty verdict ─┬─ not-novel ──► park / kill (THE MARGINS)
                  └─ novel / incremental
   │
   ▼
 SCOPE: list design decisions → advocates argue each
        → decisions record (Headline: yes/no · Revisit-if triggers)
   │
   ▼
 value re-check ─┬─ not worth it ──► park / kill
                 └─ worth it
   │
   ▼
 PROPOSE: hypothesis · baselines · eval protocol · staged plan ·
          ablations · budget · KILL criteria · success criteria
          (+ optional pre-signed full-run envelope)
   │
   ▼
 ┌ GATE 1 (human) ┐ ─┬─ approve ──► spawn the project ──► THE LAB
 └────────────────┘  └─ reject  ──► revise / park / kill
```

### 4.3 The Lab — *do the project: run experiments and analyze them* (external project repo)
This is the busiest place and the one that holds **multiple projects at once** (§2.4). At the world
level each project is a **single sprite**, with its experiment workers living *inside* it (not loose
in the room); **clicking the sprite opens that project's own lab and reveals all its agents** (§8.1).
- **Covers lifecycle states:** `active` ⇄ `analysis`. **Gate 2** lives *inside* (authorizing
  full-scale runs unless a pre-signed envelope already covers them).
- **What happens:** spawn the project repo from a template (with a smoke test), then iterate. `active`
  is where the bulk of work happens — *staged* experiments (smoke → pilot → full), operator-driven
  improvement, an unattended research-loop, and **in-project ideation** (the *nested* divergent
  approach-generation, distinct from the Incubator's broad ideation). `analysis` reads the artifacts,
  verifies claims, and decides what's next. Every attempt is one ledger row + one commit; debug caps
  prevent tunnelling.
- **Enters when:** Gate 1 approves. **Leaves when:** analysis routes to writing (or kills it).
  **Round-trip:** analysis → back to active for more experiments.
- **Who works here:** orchestrator, *experiment-runner* ensemble (each in its own worktree),
  *overseer*.

```
 [GATE 1 approved]
   │
   ▼
 SPAWN PROJECT: instantiate repo from template → smoke test → state = active
   │
   ▼
 ┌──────────────── ACTIVE  (pick the next action each cycle) ─────────────────┐
 │  • experiment      SMOKE ──► PILOT ──► FULL                                 │
 │       (each promotion needs the prior stage's pre-written success criteria; │
 │        FULL needs [GATE 2] OR a PI-signed envelope)                         │
 │  • improve         draft · debug · improve · crossover                      │
 │       (explore mode adds: expand the frontier · revisit a settled decision) │
 │  • in-project ideation   divergent NEW approaches, inside the frozen set    │
 │       (surviving approaches ⇒ re-enter the proposal gate, or a new idea)     │
 │  • research-loop   runs the above unattended, never stopping within budget  │
 └───────────────────────────────┬─────────────────────────────────────────────┘
   │ plan exhausted / plateaued
   ▼
 ANALYSIS: verify every number against run artifacts → route:
   ├─ needs more experiments ──► back to ACTIVE
   ├─ solid & complete       ──► THE WRITING ROOM
   └─ doesn't pan out        ──► kill (THE MARGINS)
```

### 4.4 The Writing Room — *turn results into a reviewed paper* (hub, reading the project's artifacts)
- **Covers lifecycle states:** `writing` ⇄ `internal-review`. **Gate 3** is the door out.
- **What happens:** generate figures/tables *by script* from run artifacts; draft the paper
  evidence-first with verified citations and a claims re-audit each round; then review it — a
  **blocking mechanical claims audit** followed by a fresh-context critique ensemble with a minority
  veto. Reviewer points become evidenced responses; any point that needs data routes **back to The
  Lab** for new experiments.
- **Enters when:** analysis says "write." **Leaves when:** the ensemble accepts *and* Gate 3 approves.
  **Round-trips:** write↔review internally, and review→active for new experiments.
- **Who works here:** orchestrator, *fresh-context-reviewer* ensemble, *overseer*.

```
 results in hand
   │
   ▼
 MAKE FIGURES: figures/tables generated by scripts from run artifacts only
   │
   ▼
 WRITE PAPER: evidence-first draft · verified citations · claims re-audited each round
   │
   ▼
 INTERNAL REVIEW:
   (1) claims audit (mechanical, BLOCKING) ──fail──► back to WRITE
   (2) fresh-context critique ensemble → scores + minority veto
   │
   ▼
 per reviewer action item:
   ├─ ACCEPT            → revise text
   ├─ REBUT             → evidenced rebuttal
   └─ NEEDS-EXPERIMENT ─► back to THE LAB (active) ──┐
   │                                                 │  (loops until the
   ▼                                                 │   ensemble accepts)
 ensemble accepts  ◄──────────────────────────────────┘
   │
   ▼
 ┌ GATE 3 (human — never delegated, never signed from the dashboard) ┐ ─ approve ─► THE ARCHIVE
 └────────────────────────────────────────────────────────────────────┘
```

### 4.5 The Archive — *close out and bank the knowledge* (hub)
- **Covers lifecycle state:** `final` (terminal).
- **What happens:** a final reproducibility pass, secure the cited artifacts, and **write the findings
  back** into lab knowledge (confirmed findings / failures / open questions) so the next idea starts
  smarter. The registry row becomes `final`.
- **Enters when:** Gate 3 approves. **Leaves when:** never — it is the resting place, but its knowledge
  feeds the next Incubator.

```
 [GATE 3 approved]
   │
   ▼
 FINALIZE: reproducibility pass → secure cited artifacts
           → write-back: findings / failures / open-questions
   │
   ▼
 registry = final  (terminal) ───knowledge compounds──► next INCUBATOR
```

### 4.6 The Margins — *out of play* (reachable from anywhere)
- **Covers lifecycle states:** `parked`, `killed`.
- **What happens:** `park` = set aside, resumable later with PI approval. `kill` = stopped with a
  recorded reason, never resurrected without PI approval. Killing early and often is intentional — kill
  criteria are written into every proposal up front.

```
 from ANY room:
   ├─ park ─► dormant  (PI can wake it later)
   └─ kill ─► stopped, reason recorded  (PI approval needed to revive)
```

### Note on room count
The grouping above (six rooms) is a recommendation, not a hard requirement: rooms may be split finer
or merged coarser as a presentation choice. Whatever the count, two rules hold: (1) the rooms must
together cover the whole lifecycle, and (2) because populations are uneven and shifting — one room
crowded while another is empty, then reversed a week later — each room must stay **legible whether it
holds zero entities or many**.

---

## 5. Living entities

### 5.1 Ideas and projects live in the world at their current stage
Every idea or project tracked by the lab must appear in the world, placed in the room that matches its
current lifecycle state, and must move rooms as its state advances. (Per §2, all of them appear at
once.)

**Why:** this is the core of observability — the position of each piece of work *is* its status, shown
continuously and without the PI asking.

### 5.2 One character per worker thread
Every working agent or subagent (every "worker thread") must be represented by its **own single
character** in the world, visibly doing work in the place its task belongs to.

**Why:** the PI needs to see the *workers themselves*, individually — how many are active, what kind,
and where. A per-worker character makes concurrent autonomous work tangible.

### 5.3 Movement must be grounded and purposeful
Characters must move with evident purpose and stay grounded in their environment; they must not drift
or float aimlessly.

**Why:** aimless floating reads as noise and undercuts the sense that real work is happening; grounded,
intentional movement reads as activity with meaning.

### 5.4 Smooth, dynamic, characterful animation
All motion (characters and transitions) must be **smooth, fluid, and lively**, with enough character to
be engaging rather than static or stiff.

**Why:** the dashboard is something the PI leaves open and glances at often; it must be pleasant and
dynamic, not a dead diagram. Quality of motion is a first-class requirement.

---

## 6. Identity, roles, and distinguishability

### 6.1 Workers are distinguishable by role
The different **roles** an agent can play must be visually distinguishable, so the PI can tell what
*kind* of work a given character is doing at a glance.

**Why:** "an agent is busy" is far less useful than "a reviewer / a runner / a critic is busy."
Role-level distinction turns the crowd into information.

### 6.2 The orchestrator is distinct from the rest
The orchestrating agent must be visually set apart from ordinary workers.

**Why:** the orchestrator coordinates everything and is the PI's primary point of contact (§7); it must
be unmistakable.

### 6.3 Individuals of the same role are distinguishable from each other
When several workers share the same role, they must still be **told apart as individuals**, and a given
worker must keep a consistent identity over time.

**Why:** the PI needs to follow a *specific* worker (e.g. to inspect one runner among three). Identical,
indistinguishable clones make that impossible.

### 6.4 A persistent key for the role encoding
The world must include an always-available **key/legend** explaining the role encoding and showing how
many workers of each role are currently active.

**Why:** any visual encoding of role is only useful if it can be read; the key makes it legible and
doubles as a live head-count of who is working.

---

## 7. The orchestrator as an interactive character

### 7.1 The orchestrator is a character you communicate with
The orchestrator must be an **in-world character that the PI interacts with to send messages and
commands** — not a detached button or menu divorced from the scene.

**Why:** the PI thinks of "telling the lab what to do" as addressing the thing that runs it. Embodying
the orchestrator as something you talk to makes commanding feel natural and keeps interaction inside
the world rather than bolted on beside it.

### 7.2 The orchestrator reflects the lab's state and attention
The orchestrator character should respond to what is happening and indicate where the lab's attention
currently is.

**Why:** it becomes a single, glanceable summary of the lab's overall condition and focus.

---

## 8. Inspection and per-project visibility

### 8.1 Each project has its own isolated working view
The PI must be able to enter a **dedicated, isolated view of a single project** and see that project's
current workers operating within it, while the rest of the world keeps running (§2.4). The entry point
is the project's own sprite: in the lab room each project is a single character, and **clicking it opens
that project's lab** (its workers live inside it, hidden from the world overview until you drill in).

**Why:** when one project is the focus, the PI needs to concentrate on its workers and activity without
the rest of the world's crowd in the way — the "project as its own little lab" view.

### 8.2 Clicking a worker reveals what it has done
Selecting any worker character must open a window/panel showing **what that worker has done and is
doing** — its own history of actions.

**Why:** the world shows *that* work is happening; the PI must be able to drill into *what exactly* a
specific worker did, on demand, to understand and trust it.

### 8.3 A worker's history must be its own, cleanly separated
The history shown for a worker must contain that worker's actions only, separated from every other
worker's.

**Why:** mixed or interleaved logs are unreadable; per-worker separation is what makes inspection
meaningful.

### 8.4 A per-project list view
Alongside the world, the PI must be able to see projects as a **plain list/cards view** with their
exact state and quick controls, for when they want details rather than the scene.

**Why:** the spatial world is great for *at a glance*; a list is better for *exact sub-state and direct
action* on a specific project.

---

## 9. Traceability, nesting, and per-workflow tracking

### 9.1 Maximal traceability — every agent logs every action
Throughout the lab, **all agents and subagents must log all of their actions**, and the dashboard must
be backed by those logs. Traceability is to be maximised, not sampled.

**Why:** trustworthy autonomy requires that nothing the lab does is invisible. Complete action logs are
the foundation the worker characters and the inspection window (§8.2) are built on, and they let the PI
reconstruct exactly what happened and why.

### 9.2 Process nesting must be represented and followable
The lab's work nests: a long campaign contains many projects; a project contains rounds of in-project
iteration; a round spawns ensembles of subagents. The dashboard must make this **nesting visible and
navigable**, so the PI can follow which outer process a given piece of work belongs to and drill from
the whole down to the individuals.

It must also distinguish the **kinds of ideation**: ideating broadly on new project directions (the
Incubator) versus ideating on new *approaches within* an existing project (inside The Lab). These are
different activities at different nesting levels and must be tellable apart.

**Why:** without a sense of nesting, the PI sees a flat soup of activity and cannot tell a top-level
campaign step from a deep sub-task, or broad ideation from in-project ideation. The whole point of the
lab is that it composes processes; the dashboard has to show that structure.

### 9.3 Every key workflow must be visually trackable and verifiable
For each of the lab's key ways of running, the dashboard must provide a **clear visual way to track and
verify it** — to see it is running, follow its progress through the rooms, and tell *progressing* from
*stuck*. This must cover, at minimum:

- the **full end-to-end automated workflow** (a hands-off campaign carried across the whole lifecycle,
  many ideas at once),
- the **single-step workflows** (running exactly one stage, then stopping),
- the **in-project experimental-iteration workflow** (a project improving itself over repeated rounds,
  including ideating new approaches within itself).

**Why:** "you can watch it" must be true for *every* important way the lab can run, not just the common
case. Each workflow should have a deliberate visual story so the PI can confirm it is doing what it
should — this is how the PI verifies autonomous runs.

### 9.4 At-a-glance live status
The dashboard must offer an **at-a-glance summary** of what is live right now (such as how much is
running, what is waiting on the PI, and how many agents are working), readable without navigating
anywhere.

**Why:** the PI should be able to learn the lab's overall state in a single glance; tracking should not
always require hunting through the world.

### 9.5 Everything updates live
The world and all of the above must reflect the lab's actual state in **near-real-time**, updating on
their own as the lab works.

**Why:** a stale dashboard is worse than none — it misleads. Observability only counts if it is current.

---

## 10. Control surface

### 10.1 The PI can command the lab from the dashboard
The PI must be able to issue instructions from within the dashboard — both structured commands and
free-text notes — directed at the lab as a whole or at a chosen project.

**Why:** seeing without steering is half a tool. The dashboard must let the PI act on what they observe,
in the moment, from the same place.

### 10.2 The PI can resolve the human decision points
Where the lab pauses for an explicit human decision (a gate doorway, §4), the dashboard must let the PI
**act on the decisions appropriate to handle here**, and must clearly surface every decision waiting on
them.

**Why:** the human decision points are the moments the lab cannot proceed without the PI; the dashboard
must make them impossible to miss and convenient to act on.

### 10.3 Read-only inspection on demand
The PI must be able to run **read-only, side-effect-free checks** from the dashboard and see their
output.

**Why:** sometimes the PI wants a precise read of the underlying state, on demand, without changing
anything — inspection that is guaranteed safe.

### 10.4 The control surface must be honest about its limits
The dashboard must be **honest about what it can and cannot do**. It must not present itself as able to
perform actions it cannot actually perform directly, and it must make clear when an instruction is
*queued for* an agent rather than executed immediately. Certain decisions are reserved and must never be
made from the dashboard.

**Why:** a control surface that overstates its power produces false confidence and unsafe actions. The PI
must always know whether something *happened* or was merely *requested*, and which levers are
intentionally unavailable here.

---

## 11. Non-functional requirements

### 11.1 Optional and non-intrusive
The dashboard must be **optional**: the lab must function completely without it, and removing the
dashboard must change nothing about how the lab works. The logging that powers it must be best-effort and
must **never interfere with or block** the lab's actual work.

**Why:** the dashboard is a convenience layered on top of the lab, not a dependency of it. The lab's
correctness can never hinge on an optional viewer, and observing work must never slow or break it.

### 11.2 Lightweight presentation, no heavy dependencies
The visualisation must be achieved with **lightweight, 2D/2.5D techniques and no heavy 3D engine**. It
should not require a heavyweight rendering dependency or a build step to run.

**Why:** the desired look is achievable without that weight, and keeping the dashboard small and
dependency-free keeps it easy to run and maintain, faithful to the lab's no-build, self-contained ethos.

### 11.3 Local and self-contained
The dashboard must run **locally** and work without external network services.

**Why:** it is the PI's private control surface over their own lab; it should not depend on, or leak to,
anything outside the machine it runs on.

### 11.4 Performance and graceful degradation
The world must stay **smooth and responsive** even as the number of entities grows, degrading gracefully
when there are many (for example, by summarising crowds rather than choking on them), and it must offer a
calmer, reduced-motion presentation for environments that need one.

**Why:** the dashboard is meant to be left open and watched; it has to remain pleasant and usable at scale
and on a range of machines, never becoming sluggish or overwhelming.

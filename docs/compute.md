# Machines & compute

A lab lives on **one machine**: your laptop, a GPU box, or a cluster login node. That machine decides two
things: where the lab's agents run, and how training runs are executed. This page covers:

- running a lab on a machine you reach over SSH;
- driving several machines from one dashboard;
- describing a machine's compute, including SLURM and other schedulers.

## Where the lab can run

| Machine | Start it | Reach it |
|---|---|---|
| This computer (Windows, macOS, Linux) | double-click `Start Newts Lab`, or `uv run --with pyyaml python newts.py` | the browser opens |
| A machine you SSH into (no desktop) | `uv run --with pyyaml python newts.py --background` there | it prints the exact `ssh -N -L 8787:127.0.0.1:<port> you@host` line to run on your computer; then open `http://127.0.0.1:8787` |
| Many machines, one window | nothing to start by hand | your local dashboard → **Labs & machines** → *Add a machine* (below) |

`--background` detaches the server, so it outlives your SSH session. Agent runs have their own
supervisors and never depend on it. `--status` and `--stop` manage it. The server always binds
`127.0.0.1`, so a lab is only reachable through SSH or from its own machine.

On a machine with no desktop, *Sign in…*, *Install…* and *Open a terminal* use an **in-browser
terminal** instead of a window. It runs a real PTY on Linux and macOS, so a CLI's own login flow works
as it would in any shell, and the dashboard never sees your credentials.

## One dashboard, many machines

**Labs & machines** (click the lab name, top left) lists this computer's labs and every machine you
added:

- **Add a machine**: an SSH alias from your `~/.ssh/config` (suggested for you; `ProxyJump`, keys and
  per-host settings work as usual) or `user@hostname`. The dashboard checks it with one
  non-interactive SSH call and reports:
  - OS and architecture, CPUs and GPUs;
  - schedulers (SLURM, PBS, LSF) and SLURM partitions;
  - `uv`, `git` and the agent CLIs;
  - whether each lab folder you add is really a lab.
- **Open** a lab there:
  1. Over SSH, the dashboard starts that lab's own dashboard server on the remote
     (`newts.py --background`, so it keeps running).
  2. It holds a tunnel to it: `ssh -N -L`, supervised and reconnecting.
  3. From then on the whole UI works on that lab unchanged: runs, gates, the Library, settings, the
     terminal. All of it executes **on that machine**. The top bar says *on &lt;machine&gt;*, and editor
     links open through VS Code Remote-SSH.
- **Machines that ask for a password or a verification code** (MFA clusters): the connection runs in
  a terminal window on your computer. You sign in there and leave the window open; the page connects
  by itself. On macOS and Linux, SSH connection sharing (`ControlMaster`) means you sign in once per
  session.
- **Create a lab there**: this template's committed files are copied over SSH and set up as an empty
  lab (the remote needs `python3` and `git`). **Install uv** opens a terminal running uv's installer
  on that machine.

Disconnecting only closes the tunnel. Agents on that machine keep working, and reopening the lab shows
everything they did.

## How training runs: `compute.scheduler`

`lab/config.yaml → compute.scheduler` describes the machine. Edit it in **Settings → This machine &
compute**, which shows what was detected and offers the matching setup.

```yaml
compute:
  max_concurrent_runs: 4         # compute slots: training runs at once, lab-wide
  scheduler:
    kind: slurm                  # local | slurm | custom
    stages: [PILOT, FULL]        # SMOKE always runs where it's launched
    poll_seconds: 30
    max_queue_hours: 48
    slurm:
      partition: gpu
      account: my-lab
      gpus_per_run: 1            # → --gres=gpu:1 (or gres: "gpu:a100:1")
      mem: 32G
      time_grace_minutes: 10     # --time = the stage budget + this
      setup: ["module load cuda/12.4", "source .venv/bin/activate"]
      extra_args: ["--exclusive"]
```

With a scheduler, `scripts/run.py` **submits** a PILOT or FULL run and **waits** for it:

1. The run directory is created at once with `status: queued` and the job id. `status.py`, the research
   loop and the dashboard show it as *queued*, never as stalled.
2. `job.sh` holds the `#SBATCH` lines, the setup lines, and `run.py … --in-job` on the compute node. There
   the run behaves exactly like a local one: the budget watchdog, `metrics.jsonl`, `meta.json` and the
   registry line.
3. The submitter keeps the compute slot alive while it waits, and cancels the job (`scancel`) if it is
   stopped. A job that leaves the queue without finishing (a node failure, a pre-emption) is recorded as
   `failed` with SLURM's reason. `reconcile.py` flags a queued run whose submitter disappeared.
4. It exits with the job's result: 0 completed, 1 failed, 2 timeout. `sweep.py` and agents see the same
   synchronous run as before.

Queue time never counts against the stage budget. Gate 2 and the compute slot are checked before
submission, exactly as for a local run. Agents are told never to call `sbatch` themselves.

**Other schedulers** (PBS, LSF, a site wrapper) are described with command templates instead of code:

```yaml
    kind: custom
    custom:
      submit: "qsub {script}"      # prints the job id
      state:  "qstat {job}"        # PEND/QUEUE → queued, RUN → running, nothing → left the queue
      cancel: "qdel {job}"
      header: ["#PBS -l walltime=04:00:00", "#PBS -l select=1:ngpus=1"]
      setup:  ["module load cuda"]
```

A project can override the block in its own `control.yaml` (`compute.scheduler`), for example to ask for
more GPUs. Projects spawned before this existed get the runner via
`uv run --with pyyaml python tools/upgrade_project.py --all`. A runner file the project changed itself is
left alone and reported.

## `SYSTEM.md`: the rest of the description

Structured settings cover what code acts on. Everything else about a machine goes in `lab/SYSTEM.md`
(Settings → This machine & compute → *SYSTEM.md*), which agents read before running anything:

- data locations and scratch space;
- quotas;
- partitions to avoid;
- "never run on the login node";
- how to load the environment by hand.

It is PI-owned: agents obey it and never edit it.

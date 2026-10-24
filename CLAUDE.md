# Working in navigation_ws

Notes for Claude Code (and anyone else) working in this repo. Architecture and the topic
contract live in `ARCHITECTURE.md`; this file is about how work gets done.

## Where things happen

- **Edit and commit only on the developer laptop.** Robots (orintwo, rover) receive this
  checkout with `scripts/sync_to_robot.sh` and run it; they are never edited in place and
  never run git commands that change state (commit, pull, checkout, stash, push).
  Read-only git there is fine. A fix found while testing on a robot is made here and
  re-synced.
- **Push only after the change was tested on a robot.**
- The robot copy lives at `orintwo:/mnt/ssd/pdavid/navigation_ws` and runs under compose
  project `navbringup`. Another checkout (erc25, compose project `src`) exists on orintwo
  and is someone else's work in progress: don't touch it.
- **The laptop has 15 GB RAM and must never be run out of memory** (an uncapped build
  killed the desktop session once). Docker builds go through the capped `capped` buildx
  builder (`utils/build_memory_cap`); C++ builds run in a container use `mem_limit` and at
  most `-j4`/`--parallel-workers 4`. Heavy builds belong on orintwo.
- orintwo's root filesystem (SD card) is nearly full. Keep code, images and data on
  `/mnt/ssd` (Docker's data root is already there).

## Tests: `utils/`

Every test, benchmark, or test harness we run goes in `utils/`, one folder per test, with
a README saying what it measures, how to run it, and what the last result was. This
includes one-off harnesses (e.g. replaying a bag in place of a sensor): if it was worth
running once, it is worth keeping. Results that matter go in that README, dated.

## Conventions

- One ROS 2 package, Dockerfile and compose service per subsystem (see ARCHITECTURE.md).
- ROS 2 Humble, CycloneDDS, `ROS_DOMAIN_ID=0`, host networking. The DDS peer list is in
  `src/config/dds/cyclonedds.xml`; a new machine's IP must be added there.
- Fixed wired IPs: orintwo .210, rover .230, laptops .100/.105, Ouster 169.254.61.114.

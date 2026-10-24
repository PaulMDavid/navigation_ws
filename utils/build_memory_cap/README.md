# build_memory_cap

Checks that Docker image builds on the developer laptop cannot exhaust host RAM.

**Why:** on 2026-10-24 a local `app_LIO_SAM` build (g2o at `make -j12`, 4 × ~2.8 GB
`cc1plus`) plus a browser exhausted the laptop's 15 GB (no swap). The kernel OOM killer
took the browser and the whole Hyprland session.

**Guard:** the default buildx builder is a `docker-container` builder capped at 8 GB RAM,
no swap, CPUs 0-7. `docker build` and `docker compose build` both use it.

```
docker buildx create --name capped --driver docker-container \
  --driver-opt memory=8g,memory-swap=8g,cpuset-cpus=0-7,default-load=true --use --bootstrap
```

`docker buildx use default` reverts to the uncapped builder. Note that this only caps builds;
`docker run`/`compose up` containers need their own `mem_limit`.

## Run

    ./run.sh

Builds an image whose `RUN` writes 10 GB, logging host `MemAvailable` every second.
Pass = the build fails with `cannot allocate memory` and host memory stays healthy.

## Last result

- 2026-10-24: PASS. Build failed `ResourceExhausted: cannot allocate memory`; lowest host
  MemAvailable 5375 MB (from 12.3 GB).

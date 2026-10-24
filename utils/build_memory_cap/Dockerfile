FROM python:3.12-alpine
# Writes 10 GB in 256 MB chunks: must be OOM-killed by the builder's cgroup limit
RUN python -c "l=[]; [l.append(b'x'*(1<<28)) for _ in range(40)]; print('allocated 10 GB: NOT capped')"

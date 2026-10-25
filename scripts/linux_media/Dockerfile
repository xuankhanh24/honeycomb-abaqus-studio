FROM ubuntu:22.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update -qq && apt-get install -y --no-install-recommends \
    ca-certificates bash csh tcsh ksh lsb-release python3 python3-pexpect \
    libstdc++5 libjpeg62 libmotif-dev libglu1-mesa libgl1 libgomp1 \
    libxext6 libxrender1 libxt6 libxi6 libsm6 libice6 libncurses5 libnsl2 \
    libx11-6 libxmu6 libxpm4 && rm -rf /var/lib/apt/lists/*
COPY tui_probe.py /probe/tui_probe.py
ENV DSY_Force_OS=linux_a64
WORKDIR /tmp
CMD ["python3", "-u", "/probe/tui_probe.py"]

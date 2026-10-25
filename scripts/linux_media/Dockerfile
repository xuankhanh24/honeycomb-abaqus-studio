FROM centos:7
# Official CentOS 7 packages are archived at the project's vault after EOL.
# Keep HTTPS and package signature verification enabled.
RUN sed -i -e 's|^mirrorlist=|#mirrorlist=|' \
    -e 's|^#baseurl=http://mirror.centos.org/centos/$releasever|baseurl=https://vault.centos.org/7.9.2009|' \
    /etc/yum.repos.d/CentOS-*.repo \
    && yum install -y ca-certificates python3 python3-pip tcsh ksh redhat-lsb-core \
    libjpeg-turbo motif mesa-libGLU libXext libXrender libXt libXi libSM libICE \
    ncurses-libs libX11 libXmu libXpm compat-libstdc++-33 libpng12 libXp \
    file hostname which findutils tar gzip \
    && python3 -m pip install --no-cache-dir pexpect==4.9.0 \
    && yum clean all
COPY tui_probe.py /probe/tui_probe.py
ENV DSY_Force_OS=linux_a64
WORKDIR /tmp
CMD ["python3", "-u", "/probe/tui_probe.py"]

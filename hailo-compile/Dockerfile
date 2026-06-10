FROM --platform=linux/amd64 ubuntu:22.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y \
    python3.10 python3.10-dev python3-pip \
    libgomp1 libglib2.0-0 \
    graphviz libgraphviz-dev pkg-config libgl1 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /workspace
COPY hailo_dataflow_compiler-3.33.1-py3-none-linux_x86_64.whl .
RUN pip3 install hailo_dataflow_compiler-3.33.1-py3-none-linux_x86_64.whl
# DFC 3.33.1 需要 numpy >= 1.24（np.dtypes）
RUN pip3 install "numpy>=1.24,<2.0" "opencv-python-headless" --upgrade

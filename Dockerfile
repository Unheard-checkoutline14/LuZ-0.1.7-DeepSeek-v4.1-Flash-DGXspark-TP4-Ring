# Arm64 sibling of the 0xSero pin. Digest-pinned 2026-09-14: the dev-dsv41 tag
# drifted twice without carrying the #39173 fix (last re-push 2026-09-11).
# sha256:4a5d132a... = the multi-arch index whose arm64 leaf we verified
# running locally (all five adapter hooks + row_store/flash_mla md5 clean).
FROM lmsysorg/sglang@sha256:4a5d132a06a77c8331e15845f2e925adc788b00105097ad55409afa3f4fa4860
WORKDIR /opt/dsv41
COPY adapter /opt/dsv41/adapter
RUN g++ -O2 -Wall -Wextra -Werror -std=c++17 -shared -fPIC -pthread \
    adapter/row_store.cpp -o adapter/librow_store.so
COPY runtime/flash_mla_sm120.py /sgl-workspace/sglang/python/sglang/kernels/ops/attention/flash_mla_sm120.py
COPY boot.py /opt/dsv41/boot.py
COPY scripts /opt/dsv41/scripts
COPY tests /opt/dsv41/tests
COPY benchmarks /opt/dsv41/benchmarks
ENV PYTHONPATH=/opt/dsv41/adapter \
    MODEL_PATH=/models/DeepSeek-V4.1-Flash \
    STATE_PATH=/state OFFLOAD_MODE=nvme DSV41_CACHE_GIB=16
EXPOSE 8888
# -S: skip site (the adapter's sitecustomize imports the engine, which takes >10 s on a
# busy head and marked the container unhealthy during long prefills); health needs stdlib only.
HEALTHCHECK --interval=30s --timeout=30s --start-period=30m --retries=3 \
    CMD ["python3", "-S", "/opt/dsv41/boot.py", "health"]
ENTRYPOINT ["python3", "-u", "/opt/dsv41/boot.py"]
CMD ["run"]

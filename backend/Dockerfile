FROM ghcr.io/steamdeckhomebrew/holo-toolchain-rust:latest

RUN rustup target add bpfel-unknown-none x86_64-unknown-linux-musl \
 && cargo install bpf-linker

ENTRYPOINT [ "/backend/entrypoint.sh" ]

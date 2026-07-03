FROM ghcr.io/steamdeckhomebrew/holo-toolchain-rust:latest

ENV PATH="${CARGO_HOME}/bin:${PATH}"

RUN rustup toolchain install nightly --component rust-src \
 && rustup target add x86_64-unknown-linux-musl \
 && cargo install bpf-linker

ENTRYPOINT [ "/backend/entrypoint.sh" ]

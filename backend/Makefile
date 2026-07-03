INTIFACE_ENGINE_VERSION ?= intiface-engine-4.0.2
INTIFACE_ENGINE_FILENAME = intiface-engine-v4.0.2-linux-x64.zip
INTIFACE_ENGINE_URL = https://github.com/buttplugio/buttplug/releases/download/$(INTIFACE_ENGINE_VERSION)/$(INTIFACE_ENGINE_FILENAME)
HAPTICS_PROBE_TARGET = x86_64-unknown-linux-musl

.PHONY: all clean

all: ./out/intiface-engine haptics-probe

./out/intiface-engine:
	mkdir -p ./out
	$(MAKE) -s -C py build

.PHONY: haptics-probe
haptics-probe:
	mkdir -p ./out
	cd haptics-probe && \
	  CARGO_TARGET_X86_64_UNKNOWN_LINUX_MUSL_LINKER=x86_64-linux-gnu-gcc \
	  cargo build --release --target $(HAPTICS_PROBE_TARGET) \
	    --package haptics-probe
	cp haptics-probe/target/$(HAPTICS_PROBE_TARGET)/release/haptics-probe ./out/haptics-probe

clean:
	rm -rf ./out

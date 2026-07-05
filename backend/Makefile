export INTIFACE_ENGINE_VERSION ?= intiface-engine-4.0.2
export INTIFACE_ENGINE_FILENAME = intiface-engine-v4.0.2-linux-x64.zip
export INTIFACE_ENGINE_URL = https://github.com/buttplugio/buttplug/releases/download/$(INTIFACE_ENGINE_VERSION)/$(INTIFACE_ENGINE_FILENAME)

# haptics-probe now lives in its own repo (linux-game-haptics-router) and is
# fetched as a release asset rather than built here. No release has been cut
# yet, so this URL 404s until linux-game-haptics-router ships v0.1.0 — bump
# HAPTICS_PROBE_VERSION (or override it on the make invocation) once it has.
HAPTICS_PROBE_VERSION ?= v0.1.0
HAPTICS_PROBE_FILENAME = game-haptics-router-x86_64-unknown-linux-musl
HAPTICS_PROBE_URL = https://github.com/madrigal-eschat/linux-game-haptics-router/releases/download/$(HAPTICS_PROBE_VERSION)/$(HAPTICS_PROBE_FILENAME)

.PHONY: all clean

all: ./out/intiface-engine ./out/haptics-probe

./out/intiface-engine:
	mkdir -p ./out
	$(MAKE) -s -C py build

./out/haptics-probe:
	mkdir -p ./out
	curl -fL -o ./out/haptics-probe "$(HAPTICS_PROBE_URL)"
	chmod +x ./out/haptics-probe

clean:
	rm -rf ./out

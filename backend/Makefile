export INTIFACE_ENGINE_VERSION ?= intiface-engine-4.0.2
export INTIFACE_ENGINE_FILENAME = intiface-engine-v4.0.2-linux-x64.zip
export INTIFACE_ENGINE_URL = https://github.com/buttplugio/buttplug/releases/download/$(INTIFACE_ENGINE_VERSION)/$(INTIFACE_ENGINE_FILENAME)

# haptics-probe now lives in its own repo (linux-game-haptics-router) and is
# fetched as a release asset rather than built here. No release has been cut
# yet, so this URL 404s until linux-game-haptics-router ships v0.1.0 — bump
# HAPTICS_ROUTER_VERSION (or override it on the make invocation) once it has.
HAPTICS_ROUTER_VERSION ?= v0.1.0
HAPTICS_ROUTER_FILENAME = game-haptics-router-x86_64-unknown-linux-musl
HAPTICS_ROUTER_URL = https://github.com/madrigal-eschat/linux-game-haptics-router/releases/download/$(HAPTICS_ROUTER_VERSION)/$(HAPTICS_ROUTER_FILENAME)

.PHONY: all clean

all: ./out/intiface-engine ./out/game-haptics-router

./out/intiface-engine:
	mkdir -p ./out
	$(MAKE) -s -C py build

./out/game-haptics-router:
	mkdir -p ./out
	curl -fL -o ./out/game-haptics-router "$(HAPTICS_ROUTER_URL)"
	chmod +x ./out/game-haptics-router

clean:
	rm -rf ./out

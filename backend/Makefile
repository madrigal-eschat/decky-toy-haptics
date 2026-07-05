export INTIFACE_ENGINE_VERSION ?= intiface-engine-4.0.2
export INTIFACE_ENGINE_FILENAME = intiface-engine-v4.0.2-linux-x64.zip
export INTIFACE_ENGINE_URL = https://github.com/buttplugio/buttplug/releases/download/$(INTIFACE_ENGINE_VERSION)/$(INTIFACE_ENGINE_FILENAME)

.PHONY: all clean

# haptics-probe now lives in its own repo (linux-game-haptics-router) —
# build it there and copy the resulting binary to ./out/haptics-probe
# before packaging this plugin.
all: ./out/intiface-engine

./out/intiface-engine:
	mkdir -p ./out
	$(MAKE) -s -C py build

clean:
	rm -rf ./out

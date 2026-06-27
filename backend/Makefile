INTIFACE_ENGINE_VERSION ?= intiface-engine-4.0.2
INTIFACE_ENGINE_FILENAME = intiface-engine-v4.0.2-linux-x64.zip
INTIFACE_ENGINE_URL = https://github.com/buttplugio/buttplug/releases/download/$(INTIFACE_ENGINE_VERSION)/$(INTIFACE_ENGINE_FILENAME)

.PHONY: all clean

all: ./out/intiface-engine

./out/intiface-engine:
	mkdir -p ./out
	curl -fL -o ./out/intiface-engine.zip "$(INTIFACE_ENGINE_URL)"
	unzip -o ./out/intiface-engine.zip intiface-engine -d ./out/
	rm ./out/intiface-engine.zip
	chmod +x ./out/intiface-engine

.PHONY: clean
clean:
	rm -rf ./out

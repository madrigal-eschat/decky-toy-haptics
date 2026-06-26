INTIFACE_ENGINE_VERSION ?= v1.4.8
INTIFACE_ENGINE_FILENAME = intiface-engine-linux-x64-Release.zip
INTIFACE_ENGINE_URL = https://github.com/intiface/intiface-engine/releases/download/$(INTIFACE_ENGINE_VERSION)/$(INTIFACE_ENGINE_FILENAME)

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

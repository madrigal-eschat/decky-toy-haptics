INTIFACE_ENGINE_VERSION ?= intiface-engine-4.0.2
INTIFACE_ENGINE_FILENAME = intiface-engine-v4.0.2-linux-x64.zip
INTIFACE_ENGINE_URL = https://github.com/buttplugio/buttplug/releases/download/$(INTIFACE_ENGINE_VERSION)/$(INTIFACE_ENGINE_FILENAME)
OUT_DIR = ../out

.PHONY: build clean

build: $(OUT_DIR)/intiface-engine

$(OUT_DIR)/intiface-engine:
	mkdir -p $(OUT_DIR)
	curl -fL -o $(OUT_DIR)/intiface-engine.zip "$(INTIFACE_ENGINE_URL)"
	python3 -c "import zipfile; zipfile.ZipFile('$(OUT_DIR)/intiface-engine.zip').extract('intiface-engine', '$(OUT_DIR)/')"
	rm $(OUT_DIR)/intiface-engine.zip
	chmod +x $(OUT_DIR)/intiface-engine

clean:
	rm -f $(OUT_DIR)/intiface-engine

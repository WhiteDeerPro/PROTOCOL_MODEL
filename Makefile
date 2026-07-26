PYTHON ?= python3
UNITTEST_FLAGS ?= -q
.PHONY: \
	smoke \
	test \
	test-active \
	test-target \
	test-integration \
	test-sentinels \
	test-release \
	showcase-axi4 \
	showcase-overview

smoke:
	$(PYTHON) -m unittest $(UNITTEST_FLAGS) tests.suites.smoke

test:
	$(PYTHON) -m unittest discover -s tests -t . $(UNITTEST_FLAGS)

test-active:
	$(PYTHON) -m unittest $(UNITTEST_FLAGS) tests.suites.active

test-target:
	TEST_TARGET="$(TARGET)" $(PYTHON) -m unittest $(UNITTEST_FLAGS) tests.suites.target

test-integration:
	$(PYTHON) -m unittest $(UNITTEST_FLAGS) tests.suites.integration

test-sentinels:
	$(PYTHON) -m unittest $(UNITTEST_FLAGS) tests.suites.sentinels

test-release:
	$(PYTHON) -m unittest $(UNITTEST_FLAGS) tests.suites.release

showcase-axi4:
	$(PYTHON) showcase/demos/axi4/run.py

showcase-overview:
	$(PYTHON) showcase/materials/assets/overview/render_png.py
	$(PYTHON) -m protocol_model

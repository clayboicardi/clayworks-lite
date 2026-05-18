# Clayworks LITE — common ops Makefile
#
# Convenience wrapper around install.sh for users / contributors who prefer
# `make target` over `./install.sh --flag`. Windows-native users without
# `make` should invoke `install.ps1` directly (see README).
#
# All targets delegate to install.sh; the script remains the source of truth.

TEST_DIR ?= /tmp/clayworks-test

.PHONY: help install dry-run verify uninstall test clean

help:        ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN{FS=":.*?## "}{printf "  %-12s %s\n", $$1, $$2}'

install:     ## Install LITE into ~/.claude/ (backup-then-install)
	bash install.sh

dry-run:     ## Preview the install without writing
	bash install.sh --dry-run

verify:      ## Sanity-check the install (file presence, python3, etc.)
	bash install.sh --verify

uninstall:   ## Remove LITE-shipped files (skips your customizations)
	bash install.sh --uninstall

test:       ## Idempotency + layout test against $(TEST_DIR)
	@rm -rf $(TEST_DIR)
	bash install.sh --dry-run --claude-dir $(TEST_DIR)
	bash install.sh --claude-dir $(TEST_DIR)
	bash install.sh --claude-dir $(TEST_DIR) | tee /tmp/.cw-rerun.log
	@grep -q "already installed and unchanged" /tmp/.cw-rerun.log \
		|| (echo "ERROR: idempotency check failed"; exit 1)
	bash install.sh --verify --claude-dir $(TEST_DIR)
	bash install.sh --uninstall --claude-dir $(TEST_DIR)
	@rm -rf $(TEST_DIR) /tmp/.cw-rerun.log
	@echo ""
	@echo "OK: install -> idempotency re-run -> verify -> uninstall all passed"

clean:      ## Remove any leftover test dirs
	@rm -rf $(TEST_DIR) /tmp/.cw-rerun.log
	@echo "cleaned: $(TEST_DIR) /tmp/.cw-rerun.log"

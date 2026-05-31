.PHONY: $(wildcard *)

deps:
	cd frontend && pnpm i

frontend:
	cd frontend && pnpm run dev

TAG ?= closed
REG ?= ghcr.io/awesome56/qa-agent

dev:
	docker compose up --build

closed:
	docker build -f Dockerfile.closed -t $(REG):$(TAG) .

build-closed: closed
	@echo "Closed image built: $(REG):$(TAG) — no .py source inside"

push-closed: closed
	docker push $(REG):$(TAG)

run-closed:
	docker run --rm -p 8000:8000 --env-file .env $(REG):$(TAG)

verify-closed:
	docker run --rm $(REG):$(TAG) sh -c "find /app/app -type f | head -20; echo '---'; ls -R /app/app | head -40"

pull-lenovo:
	./scripts/pull-lenovo.sh

deploy-lenovo:
	./scripts/deploy-lenovo.sh

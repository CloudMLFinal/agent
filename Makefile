build:
	docker build -t cloudml-agent .

run:
	docker run --env-file .env cloudml-agent

dev:
	python main.py
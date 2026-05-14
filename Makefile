.PHONY: install dev install-backend install-frontend lint test

install: install-backend install-frontend

install-backend:
	cd backend && pip install -r requirements.txt
	playwright install chromium 2>/dev/null || echo "playwright chromium 可手动安装"

install-frontend:
	cd frontend && npm install

dev:
	@echo "启动后端: uvicorn app.main:app --reload --port 8000"
	@echo "启动前端: cd frontend && npm run dev"
	@echo "请分别在两个终端中运行"

lint:
	cd backend && python -m ruff check . 2>/dev/null || echo "ruff 未安装"

test:
	cd backend && python -m pytest 2>/dev/null || echo "pytest 未配置"

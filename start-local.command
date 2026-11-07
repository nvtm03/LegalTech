#!/bin/zsh
set -eu
cd "${0:A:h}"
if [[ ! -x .venv/bin/uvicorn ]]; then
  print 'Сначала установите зависимости по README.md.'
  exit 1
fi
if [[ ! -f frontend/dist/index.html ]]; then
  print 'Сначала соберите интерфейс: cd frontend && npm install && npm run build'
  exit 1
fi
print 'Приложение: http://127.0.0.1:8000'
print 'Оставьте это окно открытым. Для остановки нажмите Ctrl+C.'
exec .venv/bin/uvicorn app:app --host 127.0.0.1 --port 8000

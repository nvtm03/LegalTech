"""Этап 1: проверка моделей Gemini и Gemma на юридических задачах проекта. Результат -> results/models_test.json"""
import json
import logging
import os
import sys

from llm_layer import generate

logging.basicConfig(level=logging.INFO)

MODELS = sys.argv[1:] or [
    "gemini-2.5-flash",
    "gemini-3.8-flash",
    "gemini-3.5-flash-lite",
    "gemini-3.1-pro-preview",
    "gemma-4-31b-it",
    "gemma-4-26b-a4b-it",
]

CLAUSE = ("3.1. Оператор вправе обрабатывать персональные данные Субъекта без ограничения срока "
          "и передавать их любым третьим лицам по своему усмотрению.")
TASKS = {
    "decompose": "Разбей договор на смысловые блоки (предмет, цена, сроки, ответственность, споры, конфиденциальность). "
                 "Ответь JSON-списком блоков с полями name и summary. Текст: «Исполнитель оказывает услуги по разработке ПО. "
                 "Цена 100 000 руб., оплата в течение 30 дней. Срок 3 месяца. За просрочку неустойка 0,1% в день. "
                 "Споры решаются в Арбитражном суде г. Москвы. Стороны обязуются не разглашать конфиденциальную информацию.»",
    "risk_152fz": f"Оцени пункт на соответствие ФЗ-152 «О персональных данных»: назови риск, сошлись на норму и предложи "
                  f"исправленную формулировку. Пункт: {CLAUSE}",
}

if __name__ == "__main__":
    os.makedirs("results", exist_ok=True)
    out = []
    for m in MODELS:
        for name, prompt in TASKS.items():
            r = generate(prompt, m, retries=1, timeout=60)
            r["task"] = name
            out.append(r)
            print(f"{m:26} {name:11} ok={r['ok']} {r['latency_s']}s {r['error'][:80]!r}", flush=True)
            json.dump(out, open("results/models_test.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    json.dump(out, open("results/models_test.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)

"""Generate a self-contained report from recorded facts; never submit it."""
from datetime import datetime
from html import escape
import json
from pathlib import Path
from zoneinfo import ZoneInfo
from evaluate import summarize_category_records

ROOT = Path(__file__).resolve().parent


def render():
    experiment = json.loads((ROOT / "results/prompt_comparison.json").read_text())
    manifest = json.loads((ROOT / "data/corpus/manifest.json").read_text())
    downloaded = [r for r in manifest if r["status"] == "downloaded"]
    rows = []
    for variant, row in experiment["summary"].items():
        variant_records=[r for r in experiment['records'] if r['variant']==variant]
        if variant_records:row=summarize_category_records(variant_records)
        rows.append(f'<tr><td>{escape(variant)}</td><td>{row["successes"]}/{row["cases"]}</td><td>{row["exact_category_matches"]}/{row["cases"]}</td><td>{row["tp"]}</td><td>{row["fp"]}</td><td>{row["fn"]}</td><td>{row.get("technical_errors",0)}</td></tr>')
    source_rows = ''.join(f'<tr><td>{escape(r["company"])}</td><td>{escape(r["doc_type"])}</td><td><a href="{escape(r["url"],quote=True)}">{escape(r["id"])}</a></td><td>{"Скачан" if r["status"] == "downloaded" else escape(r.get("error", "Ошибка"))}</td></tr>' for r in manifest)
    failures = ''.join(f'<li>{escape(r["case_id"])} / {escape(r["variant"])}: {escape(r["error"])}</li>' for r in experiment['records'] if not r['ok'])
    records = escape(json.dumps(experiment, ensure_ascii=False, indent=2))
    stamp = datetime.now(ZoneInfo('Europe/Moscow')).strftime('%d.%m.%Y %H:%M МСК')
    cases = len({r['case_id'] for r in experiment['records']})
    classes = ', '.join(sorted({r['doc_type'] for r in downloaded}))
    paired_html = ''
    paired_path = ROOT / 'results/real-derived-pilot-v1.json'
    if paired_path.exists():
        paired = json.loads(paired_path.read_text())
        paired_rows = ''.join(f'<tr><td>{escape(name)}</td><td>{row["tp"]+row["tn"]}/{row["cases"]}</td><td>{row["tp"]}</td><td>{row["tn"]}</td><td>{row["fp"]}</td><td>{row["fn"]}</td><td>{row["errors"]}</td></tr>' for name,row in paired['summary'].items())
        paired_html = f'''<h2>Проверка на реальных фрагментах</h2><p>Не оценка всего документа: проверяем только заранее указанную категорию риска. Три пары из трёх компаний: исходный фрагмент и версия с одной внесённой правкой. Разметка авторская, не экспертная. Источники, точные смещения, SHA-256 и правки фиксируются в data/evaluation/pair_specs.json. Оригиналы не изменяются; обе версии остаются в одном семействе и dev-разбиении.</p>
<p>У обоих промптов одинаковые исходные блоки и модель; порядок запуска чередуется. Смысловое разбиение здесь отключено специально, чтобы отдельно проверить влияние риск-промпта. TN — правильное отсутствие целевого паттерна, а не подтверждение юридической безопасности. Ошибки API не считаются TN. Другие найденные категории не оценены, поскольку для них нет полной разметки.</p>
<div class="table-wrap"><table><thead><tr><th>Промпт</th><th>Верно / все случаи</th><th>TP</th><th>TN</th><th>FP</th><th>FN</th><th>Ошибки API</th></tr></thead><tbody>{paired_rows}</tbody></table></div>
<p>Это небольшой пилот: три независимых семейства источников, один прогон, без проверки другими моделями и без нетронутого финального теста. По нему нельзя объявить подход оптимальным. Сырые цитаты остаются локально вне Git; обезличенные метрики и параметры — results/real-derived-pilot-v1.json.</p>'''
    semantic_html = ''
    semantic_path = ROOT / 'results/semantic-smoke-v1.json'
    if semantic_path.exists():
        semantic = json.loads(semantic_path.read_text())
        semantic_html = f'<h2>Проверка смыслового разбиения</h2><p>Полное публичное согласие СберТех: {semantic["source_spans"]} исходных фрагментов объединены в {semantic["blocks"]} смысловых блоков. Полнота исходного текста: {"проверена кодом" if semantic["coverage_verified"] else "проверка не пройдена"}. Вызовов моделей: {semantic["calls"]}. Это проверка работы системы, не измерение юридической точности или качества границ на независимом корпусе.</p>'
        if semantic.get('repeat_runs'):
            counts = ', '.join(str(r['risks_count']) for r in semantic['repeat_runs'])
            semantic_html += f'<p class="note">Повторяемость пока недостаточна: два запуска на одном полном документе дали разное число замечаний ({counts}). Это наблюдение на одном документе, не статистическая оценка. Отсутствие рисков в одном ответе не подтверждает безопасность; до проверки экспертом нельзя утверждать надёжность анализатора.</p>'
    e2e_html=''
    e2e_path=ROOT/'results/e2e-reaggregated-v2.json'
    if not e2e_path.exists():e2e_path=ROOT/'results/e2e-heldout-v1.json'
    if e2e_path.exists():
        e2e=json.loads(e2e_path.read_text())
        measured=''.join(f'<tr><td>{escape(name)}</td><td>{r["successful"]}/{r["cases"]}</td><td>{r["localized_correct"]}/{r["cases"]}</td><td>{r["flagged_controls"]}</td><td>{r["cases"]-r["successful"]}</td><td>{r["boundary_tp"]}/{r["boundary_fp"]}/{r["boundary_fn"]}</td></tr>' for name,r in e2e['summary'].items())
        e2e_html=f'''<h2>Полный конвейер: отложенные составные примеры</h2><p>Шесть случаев, два не использованных в первом пилоте семейства источников: Selectel и 2ГИС. Реальный фрагмент помещён между авторскими соседними разделами; это не полный оригинальный договор. В паре изменено одно условие. Учитывается и категория, и пересечение подтверждённой цитаты с заранее размеченным местом. Границы — грубая авторская разметка трёх разделов, не экспертный стандарт. Промпт анализа рисков под этот набор не дорабатывался.</p><div class="table-wrap"><table><thead><tr><th>Модель / разбиение</th><th>Ответ получен</th><th>Верно с локализацией / все</th><th>Лишний сигнал в контроле</th><th>Технические отказы</th><th>Границы TP/FP/FN</th></tr></thead><tbody>{measured}</tbody></table></div><p>На трёх внесённых рисках абзацный вариант тоже дал 3/3: преимущество смыслового разбиения по обнаружению рисков не показано. Семантический вариант на этом наборе совпал с грубыми границами; данных мало для обобщения. Попытка Gemma завершилась таймаутом Router, поэтому её юридическое качество здесь не измерено. Технический отказ включён в общий знаменатель, но не называется ошибочным ответом модели. Исходные метки авторские, не юридическая экспертиза. Параметры и хеши кода момента запуска сохранены в results/e2e-heldout-v1.json; последующие исправления валидации не переписывают историю эксперимента.</p>'''
    demo_html=''
    demo_path=ROOT/'results/deployment.json'
    if demo_path.exists():
        demo=json.loads(demo_path.read_text())
        if demo.get('status')=='succeeded':
            audience='Пока доступно только владельцу.' if demo.get('audience')=='owner_private' else 'Доступно по ссылке.'
            demo_html=f'<h2>Развёрнутая демонстрация</h2><p><a href="{escape(demo["url"],quote=True)}">Открыть демонстрацию</a>. {audience} Это три авторских примера с сохранёнными ответами текущего анализатора, без загрузки документов и без вызовов моделей из браузера. Снимки демо сохранены 7 ноября; последующие эксперименты их не перезаписывают. Полный Python + Vue анализатор поставляется в исходниках и запускается локально с собственным API-ключом. Демо не подменяет полноценное приложение.</p>'
    comparison_html = ''
    comparison_path = ROOT/'results/model-comparison-v2.json'
    if comparison_path.exists():
        comparison=json.loads(comparison_path.read_text())
        if comparison.get('finished_at'):
            comparison_rows=''.join(f'<tr><td>{escape(name)}</td><td>{r["successful"]}/{r["cases"]}</td><td>{r["localized_correct"]}/{r["cases"]}</td><td>{r["technical_errors"]}</td><td>{r["missed_injections"]}</td><td>{r["mislocalized_findings"]}</td><td>{r["partial_results"]}</td></tr>' for name,r in comparison['summary'].items())
            comparison_html=f'''<h2>Повторное сравнение моделей — 8 ноября</h2><p>Одинаковые шесть случаев и смысловой режим, чеклист без изменения, порядок моделей чередуется по случаям. Набор уже исследовался: это диагностический повтор после исправления валидатора, а не новый независимый тест. Каждая модель проверяется один раз на случай, таймаут 180 секунд на вызов. Бюджеты входа и вывода адаптированы к ограничениям моделей; точные параметры зафиксированы в коде и его хешах.</p><div class="table-wrap"><table><thead><tr><th>Модель / разбиение</th><th>Анализ блоков получен</th><th>Верно / все</th><th>Технические отказы</th><th>Пропуск при ответе</th><th>Находки не в том месте</th><th>Без полной проверки связей</th></tr></thead><tbody>{comparison_rows}</tbody></table></div><p>Частичный результат содержит проверенные блоки и риски, но незавершённый проход связей. Технический отказ не считается ни чистым документом, ни содержательным пропуском, однако остаётся в общем знаменателе. Оценена только заранее размеченная категория, не все правовые вопросы. Причины отказов Gemma: 2 блокировки RECITATION, 3 обрезанных ответа на лимите 2048 выходных токенов, 1 ответ с лишними данными после JSON. Эти ответы не исправлялись автоматически и не принимались за успешные. Проверена совместимость данного протокола с моделью; качество её анализа рисков по этому прогону оценить нельзя. Протокол: results/model-comparison-v2.json; диагностика: results/model-comparison-diagnostics-v2.json. На таком объёме нельзя делать вывод о превосходстве или общей юридической точности.</p>'''
    html = f'''<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>LegalTech — отчёт по этапу 3</title><style>
*{{box-sizing:border-box}}body{{margin:0;background:#f3f4ee;color:#243128;font:15px/1.7 system-ui,sans-serif}}main{{max-width:1080px;margin:auto;padding:45px 28px}}h1{{font-size:38px;line-height:1.15;letter-spacing:-1px;font-weight:500;max-width:720px}}h2{{font-size:23px;font-weight:500;margin-top:40px}}h3{{font-size:17px}}.tag{{font-size:11px;letter-spacing:1.5px;color:#627344}}.note{{background:#e8edda;padding:18px;border-radius:6px;font-size:13px}}.table-wrap{{overflow:auto}}table{{border-collapse:collapse;width:100%;font-size:13px;background:white}}th,td{{text-align:left;padding:12px;border-bottom:1px solid #dde2d3;vertical-align:top}}th{{font-size:11px;color:#647654}}a{{color:#456327}}.facts{{display:flex;gap:35px;flex-wrap:wrap;margin:28px 0}}.facts strong{{display:block;font-size:30px;font-weight:500}}.facts span{{font-size:12px;color:#697962}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;font-size:11px;max-height:600px;overflow:auto;background:white;padding:16px}}li{{margin:8px 0}}.foot{{font-size:12px;color:#71816b;margin-top:35px}}details{{margin:20px 0}}summary{{cursor:pointer}}@media(max-width:600px){{main{{padding:25px 18px}}h1{{font-size:28px}}td,th{{padding:8px}}}}@media print{{body{{background:white}}main{{padding:0}}details pre{{max-height:none}}a{{color:inherit}}.table-wrap{{overflow:visible}}table{{table-layout:fixed;font-size:9px}}td,th{{overflow-wrap:anywhere;padding:6px}}h2{{break-after:avoid}}tr{{break-inside:avoid}}}}
</style></head><body><main><p class="tag">LEGALTECH / ANTEI × ИТМО / ЭТАП 3</p><h1>Первый анализатор документов подключён к Router</h1>
<p>Новиков Тимофей Витальевич · {stamp}</p>
<p class="note">Отчёт о первом исследовательском конвейере. Даты и версии экспериментов сохранены в протоколах; время ниже — сборка отчёта. Экспертная юридическая проверка не проведена. Условия доступа к демонстрации указаны ниже.</p>
<h2>Что пробовали и что получилось</h2><div class="table-wrap"><table><thead><tr><th>Подход</th><th>Результат</th><th>Вывод</th><th>Статус</th></tr></thead><tbody>
<tr><td>Router: первый синтетический эксперимент</td><td>{sum(r['ok'] for r in experiment['records'])}/{len(experiment['records'])} запросов завершились и прошли валидацию</td><td>Подключение работает; необходимо учитывать очередь и таймауты.</td><td>Частично</td></tr>
<tr><td>Простой промпт против чеклиста</td><td>{cases} парных синтетических примеров, результаты ниже</td><td>Это предварительная проверка на dev-наборе; оптимальность не доказана.</td><td>Проверено в узком объёме</td></tr>
<tr><td>Сбор публичного корпуса</td><td>Скачано {len(downloaded)} из {len(manifest)} источников. Классы: {escape(classes)}</td><td>Нужны ручная проверка извлечения и независимая разметка.</td><td>Частично</td></tr>
<tr><td>Vue + FastAPI + SQLite</td><td>Ввод текста, очередь, анализ блоков, цитаты, экспорт JSON; локальная проверка в браузере</td><td>Опубликована демонстрация трёх примеров. Новый текст анализируется локально.</td><td>Локальный прототип</td></tr>
</tbody></table></div>
<h2>Первый эксперимент: синтетические фрагменты</h2><p>Модель: {escape(experiment['model'])}. По одному запуску каждого промпта на один пример. Автоматическая подмена модели отключена. Микроучёт по множествам категорий, а не по числу формулировок. TP — ожидаемая найденная категория, FP — лишняя, FN — пропущенная. Ошибки выполнения включены в общее число запусков и вынесены отдельно; TP/FP/FN рассчитаны только по содержательным ответам. Исторический JSON первого прогона сохранён неизменным, таблица пересчитана из записей.</p>
<div class="table-wrap"><table><thead><tr><th>Промпт</th><th>Успешные вызовы</th><th>Точное совпадение категорий</th><th>TP</th><th>FP</th><th>FN при ответе</th><th>Технические отказы</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>
<p>Контрольные примеры обозначают отсутствие специально заложенной проблемы, а не юридическую безупречность. Разметка авторская. Малый размер, одна модель, одиночные прогоны и использование dev-набора не позволяют обобщать результат на реальные договоры.</p>
{paired_html}{semantic_html}{e2e_html}{comparison_html}{demo_html}
<h2>Исправления по аудиту 8 ноября</h2><p>Проверяются границы сумм и непосредственное отрицание; цитаты показываются в исходном предложении. Оговорка привязана к диапазону цитаты риска. Удаление корректно обрабатывает пустой ответ сервера; успешные шаги сохраняются при явном повторе отказавшего шага. При сбое проверки связей анализ блоков остаётся доступным с отметкой частичной готовности. История принадлежит сессии; неактивные результаты старше семи дней удаляются при обращении к приложению. Размер запросов учитывает JSON, схему и инструкции. Проверки и статус замечаний находятся в results/audit-followup-v2.json.</p><h2>Как работает прототип</h2><ol><li>Документ разбивается на исходные фрагменты по абзацам, нумерации и предложениям с сохранением смещений.</li><li>Отдельный вызов модели группирует соседние фрагменты по смыслу. Код проверяет порядок, отсутствие пропусков/повторов и собирает блоки из оригинала.</li><li>Следующий вызов анализирует риски по блокам. JSON проверяется по схеме; идентификаторы связей и цитаты проверяются кодом.</li><li>Результаты сохраняются локально в SQLite и отображаются во Vue. Доступны Router и прямой Google API, выбираемые настройкой.</li></ol>
<p>Промпт чеклиста: {escape('risk-checklist-v1')}. В API ключи не возвращаются клиенту. Старый отчёт первого этапа не изменялся.</p>
<h2>Рабочие классы рисков</h2><p>Согласия и политики исследуются по целям и объёму данных, сроку хранения, получателям, трансграничной передаче и отзыву; пользовательские соглашения — по изменению условий и ответственности. Есть категория «другое». Это заранее заданная рабочая таксономия по теме проекта, а не автоматически открытые или доказанно полные классы. Парные реальные примеры проверяют цели/объём, сроки, получателей и ответственность; выводы распространяются только на назначенную категорию каждого примера. Крупная компания не считается юридически безошибочным эталоном.</p><h2>Источники корпуса</h2><p>Снимки хранятся локально вне Git, у каждого скачанного источника записаны дата, SHA-256 оригинала и извлечённого текста. Права на документы принадлежат издателям. Крупная компания не является доказательством отсутствия рисков.</p><div class="table-wrap"><table><thead><tr><th>Компания</th><th>Класс</th><th>Источник</th><th>Фактический статус</th></tr></thead><tbody>{source_rows}</tbody></table></div>
<h2>Что не получилось и ограничения</h2><ul>{failures}<li>Часть публичных сайтов не отдала документ: ошибки сети, сертификата, перенаправления или ограничения доступа. Проверка TLS не отключалась.</li><li>Смысловые границы выбирает модель; проверки полноты текста не доказывают правильность тем или границ.</li><li>Связи проверяются отдельным проходом по оригинальным цитатам. На длинных документах отбираются до четырёх пар из ограниченного индекса блоков, поэтому полнота не гарантируется. Поиск по нормативной базе не подключён; юридическая корректность рекомендаций не проверена.</li><li>В интерфейсе пока только текст/.txt, без PDF/DOCX/OCR. Размещённое демо показывает фиксированные примеры; многопользовательский живой анализ не развёрнут.</li></ul>
<h2>Следующий этап работы</h2><ol><li>Проверить извлечённые реальные документы и разметить риски с экспертом.</li><li>Добавить парные мутации, отрицательные примеры и отдельный закрытый тест; разделять по семействам источников.</li><li>Сравнить промпты и модели с повторными прогонами, учитывать ошибки и задержку очереди.</li><li>Улучшить семантические границы и связи блоков, подключить проверяемые нормативные источники.</li><li>При необходимости онлайн-ввода развернуть защищённый живой анализатор с квотами; текущая ссылка показывает сохранённые примеры.</li></ol>
<details><summary>Сырые результаты эксперимента (встроены в этот файл)</summary><pre>{records}</pre></details>
<p class="foot">Источники фактов: results/prompt_comparison.json, data/corpus/manifest.json и локальная реализация. Автономный HTML, без внешних библиотек и сетевых запросов. Комплект подготовлен для ручной отправки студентом.</p></main></body></html>'''
    target = ROOT / 'reports/stage2-draft.html'
    target.parent.mkdir(exist_ok=True)
    target.write_text(html, encoding='utf-8')
    (target.parent/'stage3-final.html').write_text(html,encoding='utf-8')
    print(target)


if __name__ == '__main__': render()

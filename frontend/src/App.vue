<script setup>
import { computed, onMounted, onBeforeUnmount, ref } from 'vue'
import { sameInput, decodeText, request } from './analysis-state.js'
const text = ref(''), docType = ref('consent'), model = ref('gemini-3.1-flash-lite'), provider = ref('router')
const historyItems = ref([])
const health = ref(null), error = ref(''), job = ref(null), busy = ref(false), selected = ref(null)
let timer, disposed = false
const labels = { purpose_and_scope:'Цели и объём данных', retention:'Срок хранения', third_parties:'Третьи лица', cross_border:'Трансграничная передача', withdrawal:'Отзыв согласия', unilateral_changes:'Изменение условий', liability:'Ответственность', other:'Другой риск' }
const severity = {low:'Низкий', medium:'Средний', high:'Высокий', critical:'Критический'}
const draftInput = computed(()=>({text:text.value,doc_type:docType.value,model:model.value,provider:provider.value}))
const stale = computed(()=>Boolean(job.value?.result) && !sameInput(job.value.input,draftInput.value))
const result = computed(() => stale.value ? null : job.value?.result)
const visibleRisks = computed(() => (result.value?.risks || []).filter(r => !selected.value || r.block_id === selected.value))
const configured = computed(() => health.value?.[provider.value + '_configured'])
const example = '1. Цель обработки\nОператор использует имя и электронную почту для регистрации и поддержки пользователя.\n\n2. Хранение и передача\nОператор вправе хранить персональные данные без ограничения срока и передавать их любым третьим лицам по своему усмотрению.\n\n3. Обращения\nВопросы о данных можно направить на privacy@example.org.'
onMounted(async () => {
  try {
    health.value = await request('/api/health')
    const saved = new URLSearchParams(window.location.search).get('analysis') || localStorage.getItem('legaltech-last-analysis')
    if (saved) {busy.value = true; await poll(saved,true)}
  } catch {error.value='Приложение не отвечает. Проверьте, запущен ли сервер.'}
})
onBeforeUnmount(() => { disposed = true; clearTimeout(timer) })
async function poll(id, restore=false) {
  try {
    const next = await request('/api/analyses/' + id)
    if (disposed) return
    job.value = next
    if (restore && next.input) {
      text.value=next.input.text;docType.value=next.input.doc_type;model.value=next.input.model;provider.value=next.input.provider
    }
    error.value=''
    if (['queued','running'].includes(next.status)) timer = setTimeout(() => poll(id), 2000)
    else { busy.value = false; if (next.status === 'failed') error.value = next.error }
  } catch (e) {
    if (disposed) return
    if (e.status===404) {
      error.value='Анализ недоступен в этой сессии. Добавьте документ и запустите новый.'; busy.value=false; job.value=null
      localStorage.removeItem('legaltech-last-analysis');history.replaceState(null,'',window.location.pathname)
    } else {
      error.value='Связь временно прервалась. Продолжаем ожидать тот же анализ.';busy.value=true
      timer=setTimeout(()=>poll(id,restore),5000)
    }
  }
}
async function analyze() {
  if (busy.value) return
  error.value=''; selected.value=null; busy.value=true; job.value=null
  try {
    const started = await request('/api/analyses', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text:text.value,doc_type:docType.value,model:model.value,provider:provider.value})})
    if (!disposed) {job.value=started; localStorage.setItem('legaltech-last-analysis', started.id); history.replaceState(null,'','?analysis='+encodeURIComponent(started.id)); await poll(started.id)}
  } catch (e) {error.value=e.message; busy.value=false}
}
async function resume(action="resume") {
  if (!job.value?.id || busy.value) return
  if (action==='retry' && !window.confirm('Повторить неуспешный шаг новым запросом? Он расходует лимит модели. Успешные предыдущие шаги будут использованы повторно.')) return
  busy.value=true;error.value=''
  try {await request('/api/analyses/'+job.value.id+'/'+action,{method:'POST'});await poll(job.value.id)}
  catch(e){error.value=e.message;busy.value=false}
}
async function loadHistory() {
  try {historyItems.value=(await request('/api/analyses')).analyses}
  catch(e){error.value=e.message}
}
async function openHistory(id) {
  if (busy.value) return
  localStorage.setItem('legaltech-last-analysis',id)
  history.replaceState(null,'','?analysis='+encodeURIComponent(id))
  await poll(id,true)
}
async function loadFile(event) {
  const file=event.target.files?.[0]
  if (!file) return
  if (file.size>500000) {error.value='Выберите текстовый файл до 500 КБ.'; return}
  let value
  try {value=decodeText(await file.arrayBuffer())} catch {error.value='Файл не в UTF-8. Сохраните его в UTF-8 и загрузите снова.';return}
  if (value.length>120000) {error.value='Текст должен быть короче 120 000 символов.'; return}
  text.value=value; error.value=''
}
function download() {
  const blob=new Blob([JSON.stringify(result.value,null,2)],{type:'application/json'})
  const url=URL.createObjectURL(blob), a=document.createElement('a'); a.href=url; a.download='legaltech-analysis.json'; a.click(); URL.revokeObjectURL(url)
}
async function removeAnalysis() {
  if (!job.value?.id || busy.value || !window.confirm('Удалить локальный анализ и его исходный текст? Это не удаляет журналы провайдера моделей.')) return
  try {
    await request('/api/analyses/'+job.value.id,{method:'DELETE'})
    job.value=null;text.value='';selected.value=null;error.value=''
    localStorage.removeItem('legaltech-last-analysis');history.replaceState(null,'',window.location.pathname)
    await loadHistory()
  } catch(e){error.value=e.message}
}
</script>

<template>
  <main>
    <header><a class="brand" href="/">LegalTech<span> / исследовательская мастерская</span></a><span class="status">{{health ? 'Локальная версия' : 'Подключение…'}}</span></header>
    <section class="intro"><p class="eyebrow">МОДУЛЬНЫЙ АНАЛИЗ ДОКУМЕНТОВ</p><h1>От текста договора<br>к понятным рискам.</h1><p>Разберите документ на блоки и проверьте формулировки. Каждый найденный риск привязан к исходной цитате.</p></section>
    <div class="workspace">
      <section class="input-panel">
        <div class="section-heading"><h2>01 / Документ</h2><button class="text-button" :disabled="busy" @click="text=example">Вставить пример</button></div>
        <label>Тип документа<select v-model="docType" :disabled="busy"><option value="consent">Согласие на обработку ПДн</option><option value="terms">Пользовательское соглашение</option><option value="privacy">Политика конфиденциальности</option><option value="unknown">Другой документ</option></select></label>
        <label class="text-label" for="document">Текст документа <span>{{text.length.toLocaleString('ru-RU')}} / 120 000</span></label>
        <textarea id="document" v-model="text" :disabled="busy" maxlength="120000" placeholder="Вставьте текст или загрузите файл .txt…"></textarea>
        <label class="file-input">Загрузить .txt<input type="file" accept=".txt,text/plain" :disabled="busy" @change="loadFile"></label>
        <div class="settings"><label>Подключение<select v-model="provider" :disabled="busy"><option value="router">Router ANTEI</option><option value="google">Google напрямую</option></select></label><label>Модель<select v-model="model" :disabled="busy"><option v-for="m in health?.models || [model]" :key="m">{{m}}</option></select></label></div>
        <p class="privacy">При запуске текст передаётся выбранному сервису моделей. Используйте публичные или синтетические документы. Результат сохраняется локально.</p>
        <p v-if="health && !configured" class="error" role="alert">Ключ выбранного подключения ещё не настроен.</p>
        <button class="primary" :disabled="busy || text.trim().length<20 || !configured" @click="analyze">{{busy ? 'Анализируем документ…' : 'Проанализировать документ'}}<span aria-hidden="true">↗</span></button>
        <p v-if="busy" class="muted" role="status">{{({segmentation:'Выделяем смысловые блоки.',risk_analysis:'Проверяем формулировки.',relations:'Проверяем связи разделов.'})[job?.progress?.stage] || 'Задача в работе.'}} {{job?.progress?.total ? `${job.progress.done} из ${job.progress.total}.` : ''}} Очередь моделей может занять несколько минут.</p>
        <p v-if="error" class="error" role="alert">{{error}}</p>
        <button v-if="['failed','partial'].includes(job?.status) && !busy" class="text-button" @click="resume(job.retry_action)">{{job.retry_action==='retry' ? 'Повторить неуспешный шаг (новый запрос)' : 'Возобновить ожидание прежней задачи'}}</button>
        <details v-if="!busy" @toggle="loadHistory"><summary>История этой сессии (до 7 дней)</summary><p v-for="item in historyItems" :key="item.id"><button class="text-button" @click="openHistory(item.id)">{{new Date(item.created_at).toLocaleString('ru-RU')}} · {{item.status}}</button></p><p class="muted">Неактивные анализы удаляются при первом обращении после 7 дней. История доступна только в этой сессии браузера.</p></details>
        <p v-if="job && !busy"><button class="text-button" @click="removeAnalysis">Удалить локальный анализ</button></p>
      </section>
      <section class="output-panel" aria-live="polite">
        <div class="section-heading"><h2>02 / Результат</h2><button v-if="result" class="text-button" @click="download">Скачать JSON ↓</button></div>
        <p v-if="stale" class="notice">Текст или настройки изменены. Предыдущий результат скрыт — запустите анализ новой версии.</p>
        <div v-if="!result" class="empty"><span class="empty-mark" aria-hidden="true">§</span><h3>{{busy ? 'Проверяем формулировки' : 'Здесь появится разбор'}}</h3><p>{{busy ? 'Сопоставляем риски с точными цитатами исходного текста.' : 'Добавьте документ слева или начните с короткого примера.'}}</p><div class="steps"><span>Блоки документа</span><span>Возможные риски</span><span>Что проверить</span></div></div>
        <template v-else>
          <div class="metrics"><div><strong>{{result.blocks.length}}</strong><span>блоков</span></div><div><strong>{{result.risks.length}}</strong><span>возможных рисков</span></div><div><strong>{{result.calls.reduce((s,c)=>s+c.latency_s,0).toFixed(1)}} с</strong><span>вызовы моделей</span></div></div>
          <p class="notice">Это исследовательский разбор, требующий проверки юристом. Отсутствие найденных рисков не подтверждает безопасность документа.</p>
          <p v-if="result.partial" class="notice">Анализ блоков сохранён, но проверка связей не завершена: {{result.relation_review?.error}}. Связи требуют отдельной проверки.</p>
          <p v-if="result.relation_review?.status==='no_candidates'" class="notice">Модель не выбрала пары для проверки связей. Отсутствие противоречий не установлено.</p>
          <h3>Блоки документа</h3><div class="block-tabs"><button :class="{active:!selected}" @click="selected=null">Все риски</button><button v-for="b in result.blocks" :key="b.id" :class="{active:selected===b.id}" @click="selected=selected===b.id?null:b.id">{{b.id}} · {{b.title}}</button></div>
          <details v-for="b in result.blocks.filter(b=>!selected || b.id===selected)" :key="b.id" class="block"><summary>{{b.title}}</summary><p>{{b.summary}}</p><pre>{{b.text}}</pre></details>
          <h3>Что стоит проверить</h3><p v-if="!visibleRisks.length" class="muted">В выбранных блоках модель не отметила рисков.</p>
          <article v-for="(r,i) in visibleRisks" :key="i" class="risk"><div class="risk-heading"><span>{{labels[r.category]}}</span><span class="badge" :class="r.severity">{{severity[r.severity]}}</span></div><blockquote v-if="r.context">{{r.context.slice(0,r.quote_start-r.context_start)}}<mark>{{r.quote}}</mark>{{r.context.slice(r.quote_end-r.context_start)}}</blockquote><blockquote v-else>{{r.quote}}</blockquote><p>{{r.reason}}</p><p v-if="r.context_status==='review_with_related_clause'" class="notice">К процитированному условию найдена оговорка. Рассмотрите замечание вместе со связанной формулировкой ниже.</p><div class="suggestion"><span>Рекомендация для проверки</span><p>{{r.suggestion}}</p></div><small>Источник: {{r.block_id}}<template v-if="r.related_block_ids.length"> · Связи: {{r.related_block_ids.join(', ')}}</template><template v-if="r.related_relation_ids?.length"> · Подтверждённые связи: {{r.related_relation_ids.join(', ')}}</template></small></article>
          <h3 v-if="result.relation_review?.status==='completed'">Связи и оговорки между разделами</h3>
          <p v-if="result.relation_review?.status==='completed'" class="muted">Это сопоставление условий для проверки человеком. Оговорка может уточнять общий пункт и сама по себе не является риском. Для длинного документа проверяются до четырёх выбранных пар.<template v-if="result.relation_review.review_groups_completed!=null"> Завершено групп проверки: {{result.relation_review.review_groups_completed}}. Блоков в индексе: {{result.relation_review.index_blocks}} из {{result.relation_review.total_blocks}}.</template></p>
          <p v-if="result.relation_review?.status==='completed' && !result.relations?.length" class="muted">Модель не указала подтверждённых связей в проверенных парах. Это не доказывает отсутствие противоречий.</p>
          <article v-for="(edge,i) in result.relations || []" :key="'edge'+i" class="risk">
            <strong>{{edge.id ? edge.id+' · ' : ''}}{{({exception:'Оговорка или исключение',contradiction:'Возможное противоречие',dependency:'Связанные условия'})[edge.kind]}}</strong>
            <blockquote>{{edge.left_quote}}</blockquote><small>{{edge.left_id}}</small>
            <blockquote>{{edge.right_quote}}</blockquote><small>{{edge.right_id}}</small><p>{{edge.explanation}}</p>
          </article>
          <details class="limitations"><summary>Как читать результат и ограничения</summary><ul><li v-for="item in result.limitations" :key="item">{{item}}</li></ul><p>Промпт: {{result.prompt_version}} · {{result.calls.map(c=>c.served_by).join(', ')}}</p></details>
        </template>
      </section>
    </div><footer>LegalTech · ANTEI × ИТМО <span>Первая версия / анализ текста</span></footer>
  </main>
</template>
